# Cache Service Implementation

## Overview

The cache service provides a high-performance caching layer for OpenNotebookLM, improving query response times and reducing computational costs. It supports both Redis and in-memory caching with automatic fallback.

## Features

### 1. Multi-Level Caching
- **Query Results**: Cache complete RAG query responses
- **Embeddings**: Cache computed text embeddings
- **Document Chunks**: Cache processed document chunks

### 2. Backend Support
- **Redis**: Primary cache backend for distributed caching
- **In-Memory**: Fallback cache for development/single-instance deployments
- **Automatic Fallback**: Seamlessly switches to in-memory if Redis is unavailable

### 3. Cache Management
- **TTL Support**: Configurable time-to-live for cache entries
- **Pattern-Based Clearing**: Clear cache entries matching specific patterns
- **Invalidation**: Invalidate cache by project or document ID
- **Statistics**: Track cache hits, misses, and performance metrics

## Architecture

```
┌─────────────────────────────────────┐
│         Application Layer           │
├─────────────────────────────────────┤
│          Cache Service              │
│  ┌─────────────────────────────┐   │
│  │   High-Level Methods        │   │
│  │  - cache_query_result()     │   │
│  │  - cache_embedding()        │   │
│  │  - cache_chunk()            │   │
│  └─────────────────────────────┘   │
│  ┌─────────────────────────────┐   │
│  │   Low-Level Methods         │   │
│  │  - get()                    │   │
│  │  - set()                    │   │
│  │  - delete()                 │   │
│  │  - clear()                  │   │
│  └─────────────────────────────┘   │
├─────────────────────────────────────┤
│        Cache Backend                │
│  ┌──────────┐    ┌──────────┐      │
│  │  Redis   │ OR │ In-Memory│      │
│  └──────────┘    └──────────┘      │
└─────────────────────────────────────┘
```

## Integration Points

### 1. RAG Service Integration

The RAG service uses caching to store and retrieve query results:

```python
# In rag.py
def query(self, db, query, project_id, use_cache=True):
    if use_cache and cache_service:
        # Check cache first
        cache_key = self._generate_cache_key(...)
        cached_result = cache_service.get_cached_query(project_id, cache_key)
        if cached_result:
            return cached_result
    
    # Process query...
    
    # Cache the result
    if use_cache and cache_service:
        cache_service.cache_query_result(project_id, cache_key, response)
```

### 2. Embeddings Service Integration

The embeddings service caches computed embeddings:

```python
# In embeddings.py
def generate_embedding(self, text, use_cache=True):
    if use_cache and cache_service:
        # Check cache
        cache_key = hashlib.sha256(f"{text}_{normalize}".encode()).hexdigest()
        cached = cache_service.get_cached_embedding("text_embed", cache_key)
        if cached is not None:
            return cached
    
    # Generate embedding...
    
    # Cache the result
    if use_cache and cache_service:
        cache_service.cache_embedding("text_embed", cache_key, embedding)
```

## API Endpoints

### Cache Management

- `GET /api/cache/health` - Check cache health status
- `GET /api/cache/stats` - Get cache statistics
- `DELETE /api/cache/clear` - Clear cache entries (with optional pattern)
- `DELETE /api/cache/invalidate/project/{project_id}` - Invalidate project cache
- `DELETE /api/cache/invalidate/document/{document_id}` - Invalidate document cache
- `POST /api/cache/warmup/{project_id}` - Warm up cache for a project

## Configuration

### Environment Variables

```bash
# Redis configuration (optional)
REDIS_URL=redis://localhost:6379/0
REDIS_MAX_CONNECTIONS=50
REDIS_SOCKET_TIMEOUT=5

# Cache TTL settings (seconds)
CACHE_QUERY_TTL=3600      # 1 hour for query results
CACHE_EMBEDDING_TTL=7200  # 2 hours for embeddings
CACHE_CHUNK_TTL=7200      # 2 hours for chunks
```

### Cache Key Structure

Cache keys follow a hierarchical structure:

```
query:{project_id}:{query_hash}
embedding:{document_id}:{chunk_id}
chunk:{document_id}:{chunk_id}
```

## Performance Metrics

### Cache Hit Rate

The cache service tracks hit rate to measure effectiveness:

```python
hit_rate = (hits / (hits + misses)) * 100
```

### Memory Usage

For Redis backend:
- Monitor `used_memory_human` metric
- Set `maxmemory` policy for eviction

For in-memory backend:
- Simple dictionary storage
- No automatic eviction (manual clearing required)

## Best Practices

### 1. Cache Invalidation

Always invalidate cache when:
- Documents are updated or deleted
- Project settings change
- Embeddings are regenerated

### 2. TTL Settings

Set appropriate TTL values based on:
- Data volatility
- Storage capacity
- Query patterns

### 3. Cache Warming

Pre-populate cache for:
- Frequently accessed queries
- Common document embeddings
- Popular projects

## Testing

### Unit Tests

Run cache service tests:
```bash
python backend/test_cache_integration.py
```

### API Tests

Test cache endpoints:
```bash
python backend/test_cache_api.py
```

## Monitoring

### Key Metrics to Monitor

1. **Cache Performance**
   - Hit rate
   - Response time improvement
   - Cache size

2. **Resource Usage**
   - Memory consumption
   - Network bandwidth (Redis)
   - CPU usage

3. **Error Rates**
   - Connection failures
   - Serialization errors
   - Timeout errors

## Future Enhancements

1. **Advanced Features**
   - Multi-tier caching (L1/L2)
   - Cache compression
   - Distributed cache synchronization

2. **Optimization**
   - Smart cache preloading
   - Adaptive TTL based on usage patterns
   - Cache size optimization

3. **Analytics**
   - Query pattern analysis
   - Cache effectiveness reporting
   - Cost savings calculation

## Troubleshooting

### Common Issues

1. **Redis Connection Failed**
   - Check Redis server is running
   - Verify connection URL
   - Check firewall settings

2. **High Memory Usage**
   - Configure Redis maxmemory
   - Implement cache eviction policies
   - Reduce TTL values

3. **Low Hit Rate**
   - Analyze query patterns
   - Adjust cache key generation
   - Increase TTL for stable data

## Conclusion

The cache service significantly improves OpenNotebookLM's performance by reducing redundant computations and database queries. With support for both Redis and in-memory caching, it provides flexibility for different deployment scenarios while maintaining high performance and reliability.
