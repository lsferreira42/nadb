# NADB Blog Engine

A simple but powerful blog engine built with NADB (Not A Database) using Redis as the backend storage. This example demonstrates how to build a complete web application using NADB's advanced features.

## Features

- 📝 **Create, Edit, Delete Posts** - Full CRUD operations for blog posts
- 🏷️ **Tag System** - Organize posts with tags for easy categorization
- 🔍 **Tag-based Search** - Find posts by clicking on tags
- 📊 **Admin Panel** - Manage all posts from a single interface
- 💾 **Backup System** - Create backups of your blog data
- 📱 **Responsive Design** - Works on desktop and mobile devices
- ⚡ **Fast Performance** - Powered by Redis and NADB's intelligent caching
- 🔄 **ACID Transactions** - Data consistency for all operations
- 📈 **Statistics** - View blog and system statistics

## Architecture

This blog engine showcases NADB's capabilities:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Flask Web     │    │      NADB       │    │      Redis      │
│   Application   │◄──►│   Key-Value     │◄──►│    Backend      │
│                 │    │     Store       │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │              ┌─────────────────┐              │
         │              │  Advanced       │              │
         └──────────────┤  Features:      │──────────────┘
                        │  • Transactions │
                        │  • Backup       │
                        │  • Indexing     │
                        │  • Caching      │
                        │  • Logging      │
                        └─────────────────┘
```

## Requirements

- Python 3.7+
- Redis server running on localhost:6379
- Flask
- NADB with Redis support

## Installation

1. **Install dependencies:**
   ```bash
   pip install Flask nadb[redis]
   ```

2. **Start Redis server:**
   ```bash
   # macOS (with Homebrew)
   brew install redis
   brew services start redis
   
   # Ubuntu/Debian
   sudo apt-get install redis-server
   sudo systemctl start redis
   
   # Or run Redis in Docker
   docker run -d -p 6379:6379 redis:alpine
   ```

3. **Run the blog:**
   ```bash
   python blog.py
   ```

4. **Open your browser:**
   - Blog: http://localhost:5000
   - Admin: http://localhost:5000/admin
   - Create Post: http://localhost:5000/create

## Usage

### Creating Posts

1. Go to http://localhost:5000/create
2. Fill in the title, content (Markdown supported), author, and tags
3. Choose whether to publish immediately or save as draft
4. Click "Create Post"

### Managing Posts

1. Go to http://localhost:5000/admin
2. View all posts (published and drafts)
3. Edit, delete, or view individual posts
4. Create backups of your blog data
5. View blog statistics

### Organizing with Tags

- Add comma-separated tags when creating/editing posts
- Click on any tag to filter posts by that tag
- Tags appear in the sidebar for easy navigation

### Backup & Recovery

- Click "Create Backup" in the admin panel
- Backups are stored with compression and integrity verification
- Use the NADB API to restore from backups if needed

## Data Structure

The blog uses NADB's key-value storage with the following structure:

### Keys
- `post:{uuid}` - Individual blog posts

### Tags (for NADB indexing)
- `blog_post` - All blog posts
- `published` / `draft` - Publication status
- `tag:{tag_name}` - Individual content tags
- `author:{author_name}` - Posts by author

### Data Format
```json
{
    "id": "uuid-string",
    "title": "Post Title",
    "content": "Post content in Markdown",
    "author": "Author Name",
    "tags": ["tag1", "tag2"],
    "created_at": "2024-01-15T10:30:00",
    "updated_at": "2024-01-15T10:30:00",
    "published": true
}
```

## NADB Features Demonstrated

### 1. **Basic Operations**
```python
# Store a blog post
post_data = json.dumps(post.to_dict()).encode('utf-8')
kv_store.set(f"post:{post.id}", post_data, tags=["blog_post", "published"])

# Retrieve a post
data = kv_store.get(f"post:{post_id}")
post = json.loads(data.decode('utf-8'))

# Delete a post
kv_store.delete(f"post:{post_id}")
```

### 2. **Tag-based Queries**
```python
# Get all published posts
published_posts = kv_store.query_by_tags(["blog_post", "published"])

# Get posts by specific tag
tagged_posts = kv_store.query_by_tags(["blog_post", f"tag:{tag_name}"])
```

### 3. **Advanced Features**
```python
# Transactions for data consistency
with kv_store.transaction() as tx:
    tx.set("post:1", post_data, tags)
    tx.set("index:latest", latest_post_id)

# Create backups
backup = kv_store.create_backup("blog_backup", compression=True)

# Advanced queries with pagination
results = kv_store.query_by_tags_advanced(
    tags=["blog_post", "published"],
    page=1,
    page_size=10
)
```

### 4. **Performance Monitoring**
```python
# Get comprehensive statistics
stats = kv_store.get_stats()
print(f"Cache hit rate: {stats['cache_stats']['query_cache']['hit_rate']}")
print(f"Average query time: {stats['query_stats']['tags_and']['avg_time_ms']}ms")
```

## Configuration

### Environment Variables

- `REDIS_HOST` - Redis server host (default: localhost)
- `REDIS_PORT` - Redis server port (default: 6379)
- `REDIS_DB` - Redis database number (default: 0)
- `SECRET_KEY` - Flask secret key for sessions

### NADB Configuration

The blog is configured with:
- **Database**: `blog_engine`
- **Namespace**: `posts`
- **Buffer Size**: 2MB
- **Storage Backend**: Redis
- **Advanced Features**: All enabled (transactions, backup, indexing)
- **Cache Size**: 1000 queries

## Extending the Blog

This example can be extended with:

### Additional Features
- User authentication and authorization
- Comments system
- Post categories
- RSS feed generation
- Full-text search
- Image uploads
- Post scheduling

### NADB Enhancements
- Multiple namespaces for different content types
- TTL for temporary content (like sessions)
- Cross-backend synchronization
- Advanced backup strategies

### Example Extensions

#### Adding Comments
```python
def save_comment(post_id, comment_data):
    comment_key = f"comment:{post_id}:{comment_data['id']}"
    tags = ["comment", f"post:{post_id}", f"author:{comment_data['author']}"]
    kv_store.set(comment_key, json.dumps(comment_data).encode(), tags)

def get_post_comments(post_id):
    results = kv_store.query_by_tags(["comment", f"post:{post_id}"])
    # Process results...
```

#### Adding User Sessions
```python
def create_session(user_id):
    session_id = str(uuid.uuid4())
    session_data = {"user_id": user_id, "created_at": datetime.now().isoformat()}
    
    # Use TTL for automatic session expiration
    kv_store.set_with_ttl(
        f"session:{session_id}",
        json.dumps(session_data).encode(),
        ttl_seconds=3600,  # 1 hour
        tags=["session", f"user:{user_id}"]
    )
    return session_id
```

## Performance

This blog engine leverages NADB's performance features:

- **Intelligent Caching**: Frequently accessed posts are cached in memory
- **Connection Pooling**: Redis connections are pooled for high concurrency
- **Query Optimization**: Tag queries use optimized indexes
- **Compression**: Large posts are automatically compressed
- **Buffering**: Write operations are optimized with intelligent buffering

## Production Considerations

For production deployment:

1. **Security**: Add authentication, input validation, CSRF protection
2. **Monitoring**: Use NADB's structured logging for observability
3. **Backup**: Set up automated backup schedules
4. **Scaling**: Use Redis clustering for horizontal scaling
5. **Caching**: Add HTTP caching headers for static content

## Learning Outcomes

This example demonstrates:

- How to structure a web application using NADB
- Effective use of tags for data organization
- Integration of NADB's advanced features
- Error handling and data validation
- Performance optimization techniques
- Backup and recovery strategies

Perfect for learning how to build production-ready applications with NADB! 🚀