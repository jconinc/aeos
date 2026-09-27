"""Paid-term registers, ``paid_term_normalize_v1``, and the pure paid class fence.

A product's paid fence names three term registers (own brand, category, third-party
operator) and one allow flag per class. This module holds the one normalization algorithm,
the closed register artifact format, and the class-fence evaluation that the paid planner
and the final paid worker both run. It stores nothing and grants nothing: a pass means only
that this fence does not reject the request, never approval or spend authority.

Results carry class and surface names only. No raw term, copy, URL or payload text appears in
a result or an error, so refusals are safe to log and show.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final
from urllib.parse import unquote, urlsplit

from aeos_kernel._validation import thaw_json
from aeos_kernel.errors import ContractError
from aeos_kernel.product_policy import (
    CanonicalProductManifest,
    decode_strict_json,
    load_canonical_manifest,
)

NORMALIZATION_VERSION: Final = "paid_term_normalize_v1"
REGISTER_SCHEMA_VERSION: Final = "aeos.paid-term-register.v1"
MAX_PERCENT_DECODE_ROUNDS: Final = 4

_MALFORMED_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_URL_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
#: A scheme-less token shaped like ``host.name/path``: a provider may send a URL without a scheme.
_HOST_LIKE = re.compile(r"(?:[\w%-]+\.)+[\w%-]+(?::\d+)?(?:[/?#]|$)")
#: Where free text is split into candidate URL tokens: space, brackets and quotes.
_TOKEN_BREAK = re.compile(r"[\s()\[\]{}<>\"'`]+")
#: A punycode (IDNA A-label) name part; it is read as its Unicode name wherever it sits in text.
_A_LABEL = re.compile(r"xn--[a-z0-9-]*[a-z0-9]", re.IGNORECASE)


class TermClass(StrEnum):
    OWN_BRAND = "own_brand"
    CATEGORY = "category"
    THIRD_PARTY_OPERATOR = "third_party_operator"


class PaidFenceReason(StrEnum):
    ALLOWED = "paid_fence_allowed"
    CLASS_DISALLOWED = "paid_term_class_disallowed"
    THIRD_PARTY_EXCLUSION_MISSING = "paid_third_party_exclusion_missing"
    FORBIDDEN_PHRASE = "paid_forbidden_phrase_present"
    NORMALIZATION_UNSTABLE = "paid_term_normalization_unstable"
    REGISTER_INVALID = "paid_term_register_invalid"
    MANIFEST_INTEGRITY = "manifest_integrity_failed"


class PaidTermError(ContractError):
    """A register or input the fence cannot evaluate; ``reason_code`` is safe to show."""

    def __init__(self, reason: PaidFenceReason, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason.value


@dataclass(frozen=True, slots=True)
class NormalizedTerm:
    """The word sequence and alphanumeric skeleton that matching compares."""

    words: str
    skeleton: str

    def found_in(self, text: NormalizedTerm) -> bool:
        return f" {self.words} " in f" {text.words} " or self.skeleton in text.skeleton


def normalize_text(text: str) -> NormalizedTerm:
    """``paid_term_normalize_v1``: NFKC, full case fold, separators to one space, skeleton."""

    if not isinstance(text, str):
        raise PaidTermError(PaidFenceReason.NORMALIZATION_UNSTABLE, "input is not text")
    if not _encodes(text):
        raise PaidTermError(
            PaidFenceReason.NORMALIZATION_UNSTABLE, "input contains an unpaired surrogate"
        )
    folded = unicodedata.normalize("NFKC", text).casefold()
    mapped = "".join(
        " " if unicodedata.category(char)[0] in {"Z", "P", "C"} else char for char in folded
    )
    words = " ".join(mapped.split())
    return NormalizedTerm(words=words, skeleton="".join(char for char in words if char.isalnum()))


def _encodes(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _unquote_strict(text: str) -> str | None:
    try:
        return unquote(text, errors="strict")
    except UnicodeDecodeError:
        return None


def _percent_forms(component: str) -> list[str]:
    forms = [component]
    current = component
    for _ in range(MAX_PERCENT_DECODE_ROUNDS):
        if _MALFORMED_ESCAPE.search(current):
            raise PaidTermError(PaidFenceReason.NORMALIZATION_UNSTABLE, "a URL escape is malformed")
        decoded = _unquote_strict(current)
        if decoded is None:
            # Raised outside any handler: the decoder's exception quotes the raw bytes.
            raise PaidTermError(PaidFenceReason.NORMALIZATION_UNSTABLE, "a URL escape is not UTF-8")
        if decoded == current:
            return forms
        forms.append(decoded)
        current = decoded
    if _MALFORMED_ESCAPE.search(current) or unquote(current, errors="replace") != current:
        raise PaidTermError(
            PaidFenceReason.NORMALIZATION_UNSTABLE,
            "a URL is still percent-encoded after four decoding rounds",
        )
    return forms


def _text_forms(text: str) -> list[str]:
    """Decoding rounds of free text. ``50% off`` is text, not a malformed escape; only an
    encoding still unwinding after four rounds is refused.

    Each round first takes the NFKC form, so a compatibility character (a full-width percent sign
    or punycode name part) is decoded and read exactly like its ASCII twin, and an
    escape that decodes to one is normalized in the next round."""

    forms = [text]
    current = text
    for decoding_round in range(MAX_PERCENT_DECODE_ROUNDS + 1):
        normalized = unicodedata.normalize("NFKC", current)
        if normalized not in forms:
            forms.append(normalized)
        decoded = unquote(normalized, errors="replace")
        if decoded == normalized:
            return forms
        # Only a percent-decoding change counts as a round; the NFKC step never uses one.
        if decoding_round == MAX_PERCENT_DECODE_ROUNDS:
            raise PaidTermError(
                PaidFenceReason.NORMALIZATION_UNSTABLE,
                "provider text is still percent-encoded after four decoding rounds",
            )
        if decoded not in forms:
            forms.append(decoded)
        current = decoded
    return forms


def url_forms(url: str) -> tuple[str, ...]:
    """Every text form of a URL the fence inspects: each decoding round and both host forms."""

    if not isinstance(url, str) or not url.strip():
        raise PaidTermError(PaidFenceReason.NORMALIZATION_UNSTABLE, "a URL is empty")
    parts = _split_url(url if _URL_SCHEME.match(url) else f"https://{url}")
    if parts is None:
        # Raised outside any handler: the parser's exception quotes the URL.
        raise PaidTermError(PaidFenceReason.NORMALIZATION_UNSTABLE, "a URL cannot be parsed")
    hostname, path, query, fragment = parts
    forms: list[str] = [url]
    host_forms = _percent_forms(hostname)
    forms.extend(host_forms)
    final_host = host_forms[-1]
    if final_host:
        host_names = _idna_forms(final_host)
        if host_names is None:
            raise PaidTermError(
                PaidFenceReason.NORMALIZATION_UNSTABLE, "a URL host is not a valid domain name"
            )
        forms.extend(host_names)
    for component in (path, query, fragment):
        forms.extend(_percent_forms(component))
    return tuple(form for form in forms if form)


def _split_url(url: str) -> tuple[str, str, str, str] | None:
    try:
        parsed = urlsplit(url)
        return parsed.hostname or "", parsed.path, parsed.query, parsed.fragment
    except ValueError:
        return None


def _idna_forms(host: str) -> tuple[str, str] | None:
    try:
        ascii_host = host.encode("idna").decode("ascii")
        return ascii_host, ascii_host.encode("ascii").decode("idna")
    except UnicodeError:
        return None


@dataclass(frozen=True, slots=True)
class TermRegister:
    """One complete, owner-approved register artifact of a single term class."""

    term_class: TermClass
    artifact_version: str
    owner_decision_ref: str
    complete: bool
    terms: tuple[str, ...]
    canonical_bytes: bytes = field(repr=False)
    digest: str

    def normalized(self) -> tuple[NormalizedTerm, ...]:
        return tuple(normalize_text(term) for term in self.terms)


_REGISTER_FIELDS = frozenset(
    {
        "schema_version",
        "term_class",
        "normalization_version",
        "complete",
        "owner_decision_ref",
        "artifact_version",
        "terms",
    }
)


def _serialize(value: Any) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _decode_register(raw: bytes) -> dict[str, Any] | None:
    try:
        return decode_strict_json(raw)
    except ContractError:
        return None


def load_term_register(raw: bytes) -> TermRegister:
    """Parse one register artifact strictly; its digest is SHA-256 of the canonical bytes."""

    value = _decode_register(raw)
    if value is None:
        raise PaidTermError(PaidFenceReason.REGISTER_INVALID, "register bytes are unreadable")
    if set(value) != _REGISTER_FIELDS:
        raise PaidTermError(
            PaidFenceReason.REGISTER_INVALID, "register fields are not the closed set"
        )
    if value["schema_version"] != REGISTER_SCHEMA_VERSION:
        raise PaidTermError(PaidFenceReason.REGISTER_INVALID, "register schema version is unknown")
    if value["normalization_version"] != NORMALIZATION_VERSION:
        raise PaidTermError(PaidFenceReason.REGISTER_INVALID, "register normalization is unknown")
    if value["term_class"] not in {item.value for item in TermClass}:
        raise PaidTermError(PaidFenceReason.REGISTER_INVALID, "register class is unknown")
    if value["complete"] is not True:
        raise PaidTermError(PaidFenceReason.REGISTER_INVALID, "register is not asserted complete")
    for name in ("owner_decision_ref", "artifact_version"):
        if not isinstance(value[name], str) or not value[name].strip():
            raise PaidTermError(PaidFenceReason.REGISTER_INVALID, f"register {name} is missing")
    terms = value["terms"]
    if not isinstance(terms, list) or not all(isinstance(term, str) and term for term in terms):
        raise PaidTermError(
            PaidFenceReason.REGISTER_INVALID, "register terms must be nonempty text"
        )
    ordered = sorted(terms, key=lambda term: _serialize(term))
    if len(set(ordered)) != len(ordered):
        raise PaidTermError(PaidFenceReason.REGISTER_INVALID, "register repeats a term")
    canonical = _serialize({**value, "terms": ordered})
    register = TermRegister(
        term_class=TermClass(value["term_class"]),
        artifact_version=value["artifact_version"],
        owner_decision_ref=value["owner_decision_ref"],
        complete=True,
        terms=tuple(ordered),
        canonical_bytes=canonical,
        digest=hashlib.sha256(canonical).hexdigest(),
    )
    register.normalized()
    return register


@dataclass(frozen=True, slots=True)
class RegisterBinding:
    """The register digest and version a product manifest's paid fence names for one class."""

    digest: str
    version: str


#: The manifest ``authority.paid_fence`` key prefix for each class's register binding.
_BINDING_PREFIX: Final = {
    TermClass.OWN_BRAND: "brand",
    TermClass.CATEGORY: "category",
    TermClass.THIRD_PARTY_OPERATOR: "operator",
}


@dataclass(frozen=True, slots=True)
class PaidFenceFlags:
    """The three allow flags and the register each class must be checked against."""

    allow_brand_terms: bool
    allow_category_terms: bool
    allow_third_party_operator_terms: bool
    bindings: Mapping[TermClass, RegisterBinding]

    @classmethod
    def from_manifest(cls, paid_fence: Mapping[str, Any]) -> PaidFenceFlags:
        """Read a canonical manifest's ``authority.paid_fence``; nothing is defaulted."""

        return cls(
            allow_brand_terms=paid_fence["allow_brand_terms"],
            allow_category_terms=paid_fence["allow_category_terms"],
            allow_third_party_operator_terms=paid_fence["allow_third_party_operator_terms"],
            bindings={
                term_class: RegisterBinding(
                    digest=paid_fence[f"{prefix}_term_register_digest"],
                    version=paid_fence[f"{prefix}_term_register_version"],
                )
                for term_class, prefix in _BINDING_PREFIX.items()
            },
        )

    def allows(self, term_class: TermClass) -> bool:
        return {
            TermClass.OWN_BRAND: self.allow_brand_terms,
            TermClass.CATEGORY: self.allow_category_terms,
            TermClass.THIRD_PARTY_OPERATOR: self.allow_third_party_operator_terms,
        }[term_class]


@dataclass(frozen=True, slots=True)
class PaidSurfaces:
    """Everything a paid request would show or send. The payload is the exact provider request."""

    positive_keywords: Sequence[str] = ()
    negative_keywords: Sequence[str] = ()
    context: Sequence[str] = ()
    copy: Sequence[str] = ()
    display_urls: Sequence[str] = ()
    destination_urls: Sequence[str] = ()
    provider_payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def provider_payload_digest(self) -> str:
        return hashlib.sha256(_serialize(self.provider_payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class PaidFenceDecision:
    allowed: bool
    reason_code: str
    term_class: str | None = None
    surface: str | None = None
    normalized_input_digest: str | None = None
    provider_payload_digest: str | None = None
    manifest_digest: str | None = None


def _payload_strings(value: Any) -> Iterable[str]:
    """Every string a provider would receive, mapping keys included."""

    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            yield from _payload_strings(key)
            yield from _payload_strings(child)
    elif isinstance(value, list | tuple):
        for child in value:
            yield from _payload_strings(child)


def _payload_forms(text: str) -> list[str]:
    """A provider string is inspected as text in every decoding round and, for every URL-shaped
    token of every round, as a URL. Brackets and quotes never hide a URL; neither does encoding
    the whole URL."""

    forms: list[str] = []
    for round_text in _text_forms(text):
        forms.extend(_round_forms(round_text))
    return forms


def _round_forms(round_text: str) -> list[str]:
    forms = [round_text, _unicode_labels(round_text)]
    # A space-separated token is parsed whole, so a malformed URL refuses; the same text split
    # at brackets and quotes finds a URL a wrapper would otherwise hide, and a scheme inside a
    # token (``URL:https://…``) starts a URL of its own.
    tokens = {*round_text.split(), *_TOKEN_BREAK.split(round_text)}
    tokens |= {token[match.start() :] for token in tokens for match in _URL_SCHEME.finditer(token)}
    for token in sorted(token.rstrip(".,;:!?") for token in tokens):
        if token and (_URL_SCHEME.match(token) or _HOST_LIKE.match(token)):
            forms.extend(url_forms(token))
    return forms


def _unicode_labels(text: str) -> str:
    return _A_LABEL.sub(_unicode_label, text)


def _unicode_label(match: re.Match[str]) -> str:
    name = _decode_label(match.group().lower())
    if name is None:
        # Raised outside any handler: the codec's exception quotes the label.
        raise PaidTermError(
            PaidFenceReason.NORMALIZATION_UNSTABLE, "a punycode name part cannot be decoded"
        )
    return name


def _decode_label(label: str) -> str | None:
    try:
        return label.encode("ascii").decode("idna")
    except UnicodeError:
        return None


def _surface_texts(surfaces: PaidSurfaces) -> list[tuple[str, NormalizedTerm]]:
    texts: list[tuple[str, NormalizedTerm]] = []
    for name in ("positive_keywords", "context", "copy"):
        texts.extend((name, normalize_text(item)) for item in getattr(surfaces, name))
    for name in ("display_urls", "destination_urls"):
        for url in getattr(surfaces, name):
            texts.extend((name, normalize_text(form)) for form in url_forms(url))
    for text in _payload_strings(surfaces.provider_payload):
        texts.extend(("provider_payload", normalize_text(form)) for form in _payload_forms(text))
    return texts


def validate_registers(
    registers: Mapping[TermClass, TermRegister],
    bindings: Mapping[TermClass, RegisterBinding],
) -> dict[TermClass, tuple[NormalizedTerm, ...]]:
    """All three classes present, each the signed artifact its manifest binding names, in its own
    slot, with no empty or colliding form.

    A register is trusted only as a re-read of its own canonical bytes, so a register built in
    the caller, or one whose fields disagree with its bytes or digest, is refused. A complete
    empty register is valid: it is how a brand owner approves that a class has no terms.
    """

    if set(registers) != set(TermClass) or set(bindings) != set(TermClass):
        raise PaidTermError(
            PaidFenceReason.REGISTER_INVALID, "all three term registers are required"
        )
    seen_words: set[str] = set()
    seen_skeletons: set[str] = set()
    normalized: dict[TermClass, tuple[NormalizedTerm, ...]] = {}
    for term_class in TermClass:
        register = registers[term_class]
        if register.term_class is not term_class:
            raise PaidTermError(
                PaidFenceReason.REGISTER_INVALID, "a register is in the wrong class"
            )
        if load_term_register(register.canonical_bytes) != register:
            raise PaidTermError(
                PaidFenceReason.REGISTER_INVALID, "a register does not match its signed bytes"
            )
        binding = bindings[term_class]
        if register.digest != binding.digest or register.artifact_version != binding.version:
            raise PaidTermError(
                PaidFenceReason.REGISTER_INVALID,
                "a register is not the artifact the product policy names",
            )
        forms = register.normalized()
        for form in forms:
            if not form.skeleton:
                raise PaidTermError(
                    PaidFenceReason.REGISTER_INVALID, "a term normalizes to nothing"
                )
            if form.words in seen_words or form.skeleton in seen_skeletons:
                raise PaidTermError(
                    PaidFenceReason.REGISTER_INVALID, "two terms collide after normalization"
                )
            seen_words.add(form.words)
            seen_skeletons.add(form.skeleton)
        normalized[term_class] = forms
    return normalized


def _manifest_fence(manifest: CanonicalProductManifest) -> tuple[PaidFenceFlags, list[str]]:
    """The flags, register bindings and forbidden phrases of a manifest proven by its bytes."""

    if _reloaded(manifest.canonical_bytes) != manifest:
        raise PaidTermError(
            PaidFenceReason.MANIFEST_INTEGRITY, "the product policy does not match its bytes"
        )
    payload = thaw_json(manifest.payload)
    return (
        PaidFenceFlags.from_manifest(payload["authority"]["paid_fence"]),
        list(payload["tone_profile"]["forbidden_phrases"]),
    )


def _reloaded(canonical_bytes: bytes) -> CanonicalProductManifest | None:
    try:
        return load_canonical_manifest(canonical_bytes)
    except ContractError:
        return None


def evaluate_paid_fence(
    *,
    manifest: CanonicalProductManifest,
    registers: Mapping[TermClass, TermRegister],
    surfaces: PaidSurfaces,
) -> PaidFenceDecision:
    """Run the class fence; the planner and the final worker call exactly this function.

    The allow flags, the three register bindings and the forbidden phrases are read only from
    ``manifest``, the typed revision the host's current-policy reader returned; a caller cannot
    supply its own. Whether that revision is current and approved is the host reader's check.
    """

    try:
        flags, forbidden_phrases = _manifest_fence(manifest)
        normalized = validate_registers(registers, flags.bindings)
        phrases = [normalize_text(phrase) for phrase in forbidden_phrases]
        if any(not phrase.skeleton for phrase in phrases):
            raise PaidTermError(PaidFenceReason.REGISTER_INVALID, "a forbidden phrase is empty")
        texts = _surface_texts(surfaces)
        negatives = [normalize_text(item) for item in surfaces.negative_keywords]
    except PaidTermError as error:
        return PaidFenceDecision(allowed=False, reason_code=error.reason_code)
    payload_digest = surfaces.provider_payload_digest
    policy_digest = manifest.manifest_digest
    input_digest = hashlib.sha256(
        _serialize(
            {
                "algorithm": NORMALIZATION_VERSION,
                "surfaces": [[name, form.words] for name, form in texts],
                "negative_keywords": sorted(form.words for form in negatives),
            }
        )
    ).hexdigest()

    def refused(
        reason: PaidFenceReason, term_class: str | None, surface: str | None
    ) -> PaidFenceDecision:
        return PaidFenceDecision(
            allowed=False,
            reason_code=reason.value,
            term_class=term_class,
            surface=surface,
            normalized_input_digest=input_digest,
            provider_payload_digest=payload_digest,
            manifest_digest=policy_digest,
        )

    for surface, text in texts:
        if any(phrase.found_in(text) for phrase in phrases):
            return refused(PaidFenceReason.FORBIDDEN_PHRASE, None, surface)
        for term_class in TermClass:
            if flags.allows(term_class):
                continue
            if any(term.found_in(text) for term in normalized[term_class]):
                return refused(PaidFenceReason.CLASS_DISALLOWED, term_class.value, surface)
    if not flags.allow_third_party_operator_terms:
        excluded = {form.words for form in negatives} | {form.skeleton for form in negatives}
        for term in normalized[TermClass.THIRD_PARTY_OPERATOR]:
            if term.words not in excluded and term.skeleton not in excluded:
                return refused(
                    PaidFenceReason.THIRD_PARTY_EXCLUSION_MISSING,
                    TermClass.THIRD_PARTY_OPERATOR.value,
                    "negative_keywords",
                )
    return PaidFenceDecision(
        allowed=True,
        reason_code=PaidFenceReason.ALLOWED.value,
        normalized_input_digest=input_digest,
        provider_payload_digest=payload_digest,
        manifest_digest=policy_digest,
    )


__all__ = [
    "MAX_PERCENT_DECODE_ROUNDS",
    "NORMALIZATION_VERSION",
    "REGISTER_SCHEMA_VERSION",
    "NormalizedTerm",
    "PaidFenceDecision",
    "PaidFenceFlags",
    "PaidFenceReason",
    "PaidSurfaces",
    "PaidTermError",
    "RegisterBinding",
    "TermClass",
    "TermRegister",
    "evaluate_paid_fence",
    "load_term_register",
    "normalize_text",
    "url_forms",
    "validate_registers",
]
