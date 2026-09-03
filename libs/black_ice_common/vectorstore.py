from qdrant_client import QdrantClient
from qdrant_client.models import (
    CreateAlias,
    CreateAliasOperation,
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    PointStruct,
    SearchParams,
    VectorParams,
)

from black_ice_common.config import settings

client = QdrantClient(url=settings.qdrant_url)


def alias_target(collection: str) -> str | None:
    """Resolves an alias to its current concrete collection name, or None if the
    alias doesn't exist yet. Used by scripts/reindex_faces.py to find what to copy
    from — everyday upsert/search calls just use the alias name directly, Qdrant
    resolves it server-side."""
    for a in client.get_aliases().aliases:
        if a.alias_name == collection:
            return a.collection_name
    return None


def ensure_collection(collection: str | None = None) -> None:
    """`collection` is an alias name (defaults to settings.collection_name); the
    concrete collection created behind it is `{collection}_v1`. Re-indexing to new
    HNSW/shard params happens by creating a new versioned concrete collection and
    atomically repointing the alias — never by recreating the collection an alias
    already points to (see reindex_faces.py)."""
    collection = collection or settings.collection_name
    if alias_target(collection) is not None:
        return
    concrete_name = f"{collection}_v1"
    if not client.collection_exists(concrete_name):
        client.create_collection(
            collection_name=concrete_name,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
            hnsw_config=HnswConfigDiff(m=settings.hnsw_m, ef_construct=settings.hnsw_ef_construct),
            shard_number=settings.qdrant_shard_number,
        )
    client.update_collection_aliases(
        change_aliases_operations=[CreateAliasOperation(create_alias=CreateAlias(collection_name=concrete_name, alias_name=collection))]
    )


def upsert_face(point_id: str, embedding, identity_id: str, name: str, collection: str | None = None) -> None:
    client.upsert(
        collection_name=collection or settings.collection_name,
        points=[PointStruct(id=point_id, vector=embedding.tolist(), payload={"identity_id": identity_id, "name": name})],
    )


def search_face(embedding, limit: int = 1, collection: str | None = None):
    return client.query_points(
        collection_name=collection or settings.collection_name,
        query=embedding.tolist(),
        limit=limit,
        search_params=SearchParams(hnsw_ef=settings.hnsw_ef_search),
    ).points


def delete_identity_vectors(identity_id: str, collection: str | None = None) -> None:
    """Retention/consent revocation: remove every enrolled embedding for an identity."""
    client.delete(
        collection_name=collection or settings.collection_name,
        points_selector=Filter(must=[FieldCondition(key="identity_id", match=MatchValue(value=identity_id))]),
    )
