"""The complete fixed Cypher registry for the AEOS Memgraph adapter."""

SCHEMA_STATEMENTS = (
    "CREATE CONSTRAINT ON (n:AEOSProject) ASSERT n.project_key IS UNIQUE",
    "CREATE CONSTRAINT ON (n:AEOSSnapshot) ASSERT n.snapshot_key IS UNIQUE",
    "CREATE CONSTRAINT ON (n:AEOSEntity) ASSERT n.entity_key IS UNIQUE",
    "CREATE INDEX ON :AEOSEntity(project_id, kind)",
    "CREATE INDEX ON :AEOSEntity(project_id, entity_id)",
)

CURRENT_SNAPSHOT = """
MATCH (p:AEOSProject {project_key: $project_key})-[:CURRENT_SNAPSHOT]->(s:AEOSSnapshot)
WHERE p.project_id = $project_id AND p.vertical_id = $vertical_id
  AND p.tenant_id = $tenant_id
RETURN s.generation, s.snapshot_digest
"""

UPSERT_PROJECT = """
MERGE (p:AEOSProject {project_key: $project_key})
SET p.project_id = $project_id, p.vertical_id = $vertical_id, p.tenant_id = $tenant_id
"""

CREATE_SNAPSHOT = """
MATCH (p:AEOSProject {project_key: $project_key})
CREATE (s:AEOSSnapshot {
  snapshot_key: $snapshot_key, project_id: $project_id, vertical_id: $vertical_id,
  tenant_id: $tenant_id, generation: $generation, snapshot_digest: $snapshot_digest,
  vocabulary_digest: $vocabulary_digest, source_heads_json: $source_heads_json,
  built_at: $built_at
})
CREATE (p)-[:OWNS_SNAPSHOT {
  project_id: $project_id, vertical_id: $vertical_id, tenant_id: $tenant_id
}]->(s)
"""

CREATE_ENTITIES = """
MATCH (s:AEOSSnapshot {snapshot_key: $snapshot_key})
UNWIND $nodes AS row
CREATE (n:AEOSEntity {
  entity_key: row.entity_key, project_id: $project_id, vertical_id: $vertical_id,
  tenant_id: $tenant_id, snapshot_key: $snapshot_key, entity_id: row.entity_id,
  kind: row.kind, revision: row.revision, content_digest: row.content_digest,
  privacy_classification: row.privacy_classification, properties_json: row.properties_json
})
CREATE (s)-[:CONTAINS {
  project_id: $project_id, vertical_id: $vertical_id, tenant_id: $tenant_id
}]->(n)
"""

CREATE_EDGES = """
UNWIND $edges AS row
MATCH (source:AEOSEntity {entity_key: row.from_key})
MATCH (target:AEOSEntity {entity_key: row.to_key})
CREATE (source)-[:AEOS_RELATION {
  edge_key: row.edge_key, edge_id: row.edge_id, kind: row.kind,
  project_id: $project_id, vertical_id: $vertical_id, tenant_id: $tenant_id,
  snapshot_key: $snapshot_key,
  evidence_json: row.evidence_json, properties_json: row.properties_json
}]->(target)
"""

FLIP_CURRENT = """
MATCH (p:AEOSProject {project_key: $project_key})
MATCH (s:AEOSSnapshot {snapshot_key: $snapshot_key})
OPTIONAL MATCH (p)-[old:CURRENT_SNAPSHOT]->(:AEOSSnapshot)
DELETE old
CREATE (p)-[:CURRENT_SNAPSHOT {
  project_id: $project_id, vertical_id: $vertical_id, tenant_id: $tenant_id
}]->(s)
"""

PRUNE_OLD_SNAPSHOTS = """
MATCH (p:AEOSProject {project_key: $project_key})-[:OWNS_SNAPSHOT]->(old:AEOSSnapshot)
WHERE old.project_id = $project_id AND old.vertical_id = $vertical_id
  AND old.tenant_id = $tenant_id AND old.generation < $minimum_generation
OPTIONAL MATCH (old)-[:CONTAINS]->(entity:AEOSEntity)
DETACH DELETE entity, old
"""

NEIGHBORHOOD = """
MATCH (p:AEOSProject {project_key: $project_key})-[:CURRENT_SNAPSHOT]->(s:AEOSSnapshot)
MATCH (s)-[:CONTAINS]->(root:AEOSEntity {entity_id: $entity_id})
WHERE root.project_id = $project_id AND root.vertical_id = $vertical_id
  AND root.tenant_id = $tenant_id
MATCH (root)-[r:AEOS_RELATION]-(neighbor:AEOSEntity)
WHERE r.project_id = $project_id AND r.vertical_id = $vertical_id
  AND r.tenant_id = $tenant_id AND r.snapshot_key = s.snapshot_key
  AND neighbor.project_id = $project_id AND neighbor.vertical_id = $vertical_id
  AND neighbor.tenant_id = $tenant_id AND neighbor.snapshot_key = s.snapshot_key
RETURN r.edge_id, r.kind,
  CASE WHEN startNode(r) = root THEN 'outgoing' ELSE 'incoming' END,
  neighbor.entity_id, neighbor.kind, neighbor.revision, neighbor.content_digest,
  neighbor.properties_json
ORDER BY r.kind, neighbor.kind, neighbor.entity_id
"""
