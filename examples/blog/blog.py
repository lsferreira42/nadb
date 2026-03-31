#!/usr/bin/env python3
"""
Simple Blog Engine using NADB with Redis Backend

This example demonstrates how to build a simple blog application using NADB
for data storage with Redis as the backend. The blog supports:
- Creating, editing, and deleting posts
- Tagging posts for categorization
- Searching posts by tags
- Automatic timestamps
- Simple web interface

Requirements:
- pip install Flask nadb[redis]
- Redis server running on localhost:6379

Usage:
- python blog.py
- Open http://localhost:5000 in your browser
"""

import os
import json
import uuid
import atexit
from datetime import datetime
from flask import Flask, request, render_template, jsonify, redirect, url_for, abort

# Import NADB
from nadb import KeyValueStore, KeyValueSync

# --- NADB Setup ---
print("Initializing NADB Blog Engine...")

# Initialize synchronization engine
kv_sync = KeyValueSync(flush_interval_seconds=5)
kv_sync.start()

# Get Redis configuration from environment variables
redis_host = os.environ.get('REDIS_HOST', 'localhost')
redis_port = int(os.environ.get('REDIS_PORT', 6379))
redis_db = int(os.environ.get('REDIS_DB', 0))

# Initialize KeyValueStore with Redis backend
kv_store = KeyValueStore(
    data_folder_path='./blog_data',
    db='blog_engine',
    buffer_size_mb=2,
    namespace='posts',
    sync=kv_sync,
    storage_backend="redis",
    enable_transactions=True,    # Enable transactions for data consistency
    enable_backup=True,          # Enable backup functionality
    enable_indexing=True,        # Enable advanced indexing for fast queries
    cache_size=1000             # Cache up to 1000 queries
)

# Configure Redis connection if needed
if redis_host != 'localhost' or redis_port != 6379 or redis_db != 0:
    from storage_backends.redis import RedisStorage
    custom_redis_storage = RedisStorage(
        base_path='./blog_data',
        host=redis_host,
        port=redis_port,
        db=redis_db
    )
    kv_store.storage = custom_redis_storage

# Ensure NADB sync stops gracefully on exit
atexit.register(kv_sync.sync_exit)
print(f"NADB Blog Engine initialized with Redis at {redis_host}:{redis_port} (DB: {redis_db})")

# --- Flask App Setup ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'blog-secret-key-change-in-production')

# --- Blog Data Models ---

class BlogPost:
    """Simple blog post model."""
    
    def __init__(self, title, content, author="Anonymous", tags=None, post_id=None):
        self.id = post_id or str(uuid.uuid4())
        self.title = title
        self.content = content
        self.author = author
        self.tags = tags or []
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.published = True
    
    def to_dict(self):
        """Convert post to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'author': self.author,
            'tags': self.tags,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'published': self.published
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create BlogPost from dictionary."""
        post = cls(
            title=data['title'],
            content=data['content'],
            author=data.get('author', 'Anonymous'),
            tags=data.get('tags', []),
            post_id=data['id']
        )
        post.created_at = data.get('created_at', datetime.now().isoformat())
        post.updated_at = data.get('updated_at', post.created_at)
        post.published = data.get('published', True)
        return post

# --- Blog Helper Functions ---

def get_post_key(post_id):
    """Generate NADB key for a blog post."""
    return f"post:{post_id}"

def save_post(post):
    """Save a blog post to NADB."""
    try:
        key = get_post_key(post.id)
        post.updated_at = datetime.now().isoformat()
        
        # Prepare tags for NADB (include post type and individual tags)
        nadb_tags = ["blog_post", "published" if post.published else "draft"]
        nadb_tags.extend([f"tag:{tag}" for tag in post.tags])
        nadb_tags.append(f"author:{post.author}")
        
        # Save to NADB with tags
        value = json.dumps(post.to_dict()).encode('utf-8')
        kv_store.set(key, value, tags=nadb_tags)
        
        print(f"Saved blog post: {post.title} ({post.id})")
        return post
    except Exception as e:
        print(f"Error saving post {post.id}: {e}")
        raise

def get_post(post_id):
    """Retrieve a blog post from NADB."""
    try:
        key = get_post_key(post_id)
        data = kv_store.get(key)
        post_dict = json.loads(data.decode('utf-8'))
        return BlogPost.from_dict(post_dict)
    except KeyError:
        return None
    except Exception as e:
        print(f"Error getting post {post_id}: {e}")
        raise

def delete_post(post_id):
    """Delete a blog post from NADB."""
    try:
        key = get_post_key(post_id)
        kv_store.delete(key)
        print(f"Deleted blog post: {post_id}")
        return True
    except KeyError:
        return False
    except Exception as e:
        print(f"Error deleting post {post_id}: {e}")
        raise

def get_all_posts(limit=50, published_only=True):
    """Get all blog posts, optionally filtered by published status."""
    try:
        # Query posts using tags
        if published_only:
            results = kv_store.query_by_tags(["blog_post", "published"])
        else:
            results = kv_store.query_by_tags(["blog_post"])
        
        posts = []
        for key, metadata in results.items():
            try:
                post_data = kv_store.get(key)
                post_dict = json.loads(post_data.decode('utf-8'))
                posts.append(BlogPost.from_dict(post_dict))
            except Exception as e:
                print(f"Error loading post {key}: {e}")
                continue
        
        # Sort by creation date (newest first)
        posts.sort(key=lambda p: p.created_at, reverse=True)
        
        # Apply limit
        return posts[:limit]
    
    except Exception as e:
        print(f"Error getting all posts: {e}")
        return []

def search_posts_by_tag(tag, limit=50):
    """Search posts by a specific tag."""
    try:
        # Query using the tag format we use in NADB
        results = kv_store.query_by_tags(["blog_post", f"tag:{tag}"])
        
        posts = []
        for key, metadata in results.items():
            try:
                post_data = kv_store.get(key)
                post_dict = json.loads(post_data.decode('utf-8'))
                posts.append(BlogPost.from_dict(post_dict))
            except Exception as e:
                print(f"Error loading post {key}: {e}")
                continue
        
        # Sort by creation date (newest first)
        posts.sort(key=lambda p: p.created_at, reverse=True)
        
        return posts[:limit]
    
    except Exception as e:
        print(f"Error searching posts by tag {tag}: {e}")
        return []

def get_all_tags():
    """Get all unique tags used in blog posts."""
    try:
        # Get all blog posts and extract tags
        all_posts = get_all_posts(limit=1000, published_only=False)
        tags = set()
        
        for post in all_posts:
            tags.update(post.tags)
        
        return sorted(list(tags))
    
    except Exception as e:
        print(f"Error getting all tags: {e}")
        return []

def get_blog_stats():
    """Get blog statistics."""
    try:
        all_posts = get_all_posts(limit=1000, published_only=False)
        published_posts = [p for p in all_posts if p.published]
        draft_posts = [p for p in all_posts if not p.published]
        
        # Get NADB stats
        nadb_stats = kv_store.get_stats()
        
        return {
            'total_posts': len(all_posts),
            'published_posts': len(published_posts),
            'draft_posts': len(draft_posts),
            'total_tags': len(get_all_tags()),
            'nadb_stats': nadb_stats
        }
    except Exception as e:
        print(f"Error getting blog stats: {e}")
        return {}

# --- Flask Routes ---

@app.route('/')
def index():
    """Blog homepage showing all published posts."""
    try:
        posts = get_all_posts(limit=20, published_only=True)
        tags = get_all_tags()
        return render_template('blog.html', posts=posts, tags=tags, current_tag=None)
    except Exception as e:
        print(f"Error in index route: {e}")
        return render_template('blog.html', posts=[], tags=[], error=str(e))

@app.route('/tag/<tag>')
def posts_by_tag(tag):
    """Show posts filtered by tag."""
    try:
        posts = search_posts_by_tag(tag, limit=20)
        tags = get_all_tags()
        return render_template('blog.html', posts=posts, tags=tags, current_tag=tag)
    except Exception as e:
        print(f"Error in posts_by_tag route: {e}")
        return render_template('blog.html', posts=[], tags=[], error=str(e))

@app.route('/post/<post_id>')
def view_post(post_id):
    """View a single blog post."""
    try:
        post = get_post(post_id)
        if not post:
            abort(404)
        
        return render_template('blog.html', single_post=post, tags=get_all_tags())
    except Exception as e:
        print(f"Error in view_post route: {e}")
        abort(500)

@app.route('/admin')
def admin():
    """Admin panel for managing posts."""
    try:
        posts = get_all_posts(limit=50, published_only=False)
        stats = get_blog_stats()
        return render_template('blog.html', admin_mode=True, posts=posts, stats=stats, tags=get_all_tags())
    except Exception as e:
        print(f"Error in admin route: {e}")
        return render_template('blog.html', admin_mode=True, posts=[], stats={}, error=str(e))

@app.route('/create', methods=['GET', 'POST'])
def create_post():
    """Create a new blog post."""
    if request.method == 'GET':
        return render_template('blog.html', create_mode=True, tags=get_all_tags())
    
    try:
        # Get form data
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        author = request.form.get('author', 'Anonymous').strip()
        tags_str = request.form.get('tags', '').strip()
        published = request.form.get('published') == 'on'
        
        # Validate required fields
        if not title or not content:
            return render_template('blog.html', create_mode=True, tags=get_all_tags(), 
                                 error="Title and content are required")
        
        # Parse tags
        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        
        # Create and save post
        post = BlogPost(title=title, content=content, author=author, tags=tags)
        post.published = published
        
        save_post(post)
        
        return redirect(url_for('view_post', post_id=post.id))
    
    except Exception as e:
        print(f"Error creating post: {e}")
        return render_template('blog.html', create_mode=True, tags=get_all_tags(), error=str(e))

@app.route('/edit/<post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    """Edit an existing blog post."""
    try:
        post = get_post(post_id)
        if not post:
            abort(404)
        
        if request.method == 'GET':
            return render_template('blog.html', edit_mode=True, post=post, tags=get_all_tags())
        
        # Handle POST request (update post)
        post.title = request.form.get('title', '').strip()
        post.content = request.form.get('content', '').strip()
        post.author = request.form.get('author', 'Anonymous').strip()
        tags_str = request.form.get('tags', '').strip()
        post.published = request.form.get('published') == 'on'
        
        # Validate required fields
        if not post.title or not post.content:
            return render_template('blog.html', edit_mode=True, post=post, tags=get_all_tags(),
                                 error="Title and content are required")
        
        # Parse tags
        post.tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        
        # Save updated post
        save_post(post)
        
        return redirect(url_for('view_post', post_id=post.id))
    
    except Exception as e:
        print(f"Error editing post {post_id}: {e}")
        abort(500)

@app.route('/delete/<post_id>', methods=['POST'])
def delete_post_route(post_id):
    """Delete a blog post."""
    try:
        success = delete_post(post_id)
        if success:
            return redirect(url_for('admin'))
        else:
            abort(404)
    except Exception as e:
        print(f"Error deleting post {post_id}: {e}")
        abort(500)

@app.route('/api/stats')
def api_stats():
    """API endpoint for blog statistics."""
    try:
        stats = get_blog_stats()
        return jsonify(stats)
    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/backup', methods=['POST'])
def api_backup():
    """API endpoint to create a backup."""
    try:
        backup_id = f"blog_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_meta = kv_store.create_backup(backup_id, compression=True)
        
        return jsonify({
            'success': True,
            'backup_id': backup_meta.backup_id,
            'file_count': backup_meta.file_count,
            'total_size': backup_meta.total_size
        })
    except Exception as e:
        print(f"Error creating backup: {e}")
        return jsonify({'error': str(e)}), 500

# --- Error Handlers ---

@app.errorhandler(404)
def not_found(error):
    return render_template('blog.html', error="Page not found", tags=get_all_tags()), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('blog.html', error="Internal server error", tags=get_all_tags()), 500

# --- Main ---

if __name__ == '__main__':
    print("Starting NADB Blog Engine...")
    print("Visit http://localhost:5000 to view the blog")
    print("Visit http://localhost:5000/admin to manage posts")
    print("Visit http://localhost:5000/create to create a new post")
    
    # Create some sample posts if the blog is empty
    try:
        existing_posts = get_all_posts(limit=1)
        if not existing_posts:
            print("Creating sample blog posts...")
            
            # Sample post 1
            sample_post1 = BlogPost(
                title="Welcome to NADB Blog!",
                content="""# Welcome to NADB Blog Engine!

This is a simple blog engine built using **NADB** (Not A Database) with Redis as the backend storage.

## Features

- **Fast Storage**: Uses Redis for lightning-fast data access
- **Tagging System**: Organize posts with tags for easy categorization
- **Search**: Find posts by tags quickly
- **Admin Panel**: Easy post management interface
- **Backup Support**: Built-in backup functionality

## About NADB

NADB is a high-performance key-value store with advanced features including:
- ACID Transactions
- Backup & Recovery
- Intelligent Indexing & Caching
- Structured Logging
- Multiple Storage Backends

Visit the [NADB GitHub repository](https://github.com/lsferreira42/nadb) to learn more!

Happy blogging! 🚀""",
                author="NADB Team",
                tags=["welcome", "nadb", "tutorial"]
            )
            save_post(sample_post1)
            
            # Sample post 2
            sample_post2 = BlogPost(
                title="How to Use Tags Effectively",
                content="""# Organizing Your Blog with Tags

Tags are a powerful way to organize and categorize your blog posts. Here are some tips for using tags effectively:

## Best Practices

1. **Keep tags simple**: Use short, descriptive words
2. **Be consistent**: Use the same tag format across posts
3. **Don't over-tag**: 3-5 tags per post is usually enough
4. **Use categories**: Create broader category tags like "tutorial", "news", "review"

## Examples

- **Technology posts**: `python`, `javascript`, `tutorial`, `programming`
- **Personal posts**: `thoughts`, `life`, `travel`, `photography`
- **Business posts**: `startup`, `marketing`, `productivity`, `tips`

## Tag Navigation

Click on any tag to see all posts with that tag. This makes it easy for readers to find related content!""",
                author="Blog Admin",
                tags=["tutorial", "blogging", "tips", "organization"]
            )
            save_post(sample_post2)
            
            print("Sample posts created successfully!")
    
    except Exception as e:
        print(f"Error creating sample posts: {e}")
    
    # Run the Flask app
    app.run(debug=True, host='0.0.0.0', port=5000)