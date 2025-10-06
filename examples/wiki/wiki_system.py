#!/usr/bin/env python3
"""
Sistema de Wiki Completo usando NADB
Demonstra: versionamento, estatísticas, busca, colaboração
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import json
import uuid
import atexit
from datetime import datetime, timedelta
import re
from collections import defaultdict, Counter
import markdown
from markupsafe import Markup
import os
import sys

# Adicionar o diretório pai ao path para importar NADB
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from nadb import KeyValueStore, KeyValueSync

app = Flask(__name__)
app.secret_key = 'wiki_secret_key_change_in_production'

# --- NADB Setup ---
print("Initializing NADB Wiki System...")

# Initialize synchronization engine
kv_sync = KeyValueSync(flush_interval_seconds=5)
kv_sync.start()

# Get Redis configuration from environment variables
redis_host = os.environ.get('REDIS_HOST', 'localhost')
redis_port = int(os.environ.get('REDIS_PORT', 6379))
redis_db = int(os.environ.get('REDIS_DB', 3))  # DB separado para wiki

# Initialize KeyValueStore with Redis backend
kv_store = KeyValueStore(
    data_folder_path='./wiki_data',
    db='wiki_system',
    buffer_size_mb=2,
    namespace='pages',
    sync=kv_sync,
    storage_backend="redis"
)

# Configure Redis connection if needed
if redis_host != 'localhost' or redis_port != 6379 or redis_db != 3:
    from storage_backends.redis import RedisStorage
    custom_redis_storage = RedisStorage(
        base_path='./wiki_data',
        host=redis_host,
        port=redis_port,
        db=redis_db
    )
    kv_store.storage = custom_redis_storage

# Ensure NADB sync stops gracefully on exit
atexit.register(kv_sync.sync_exit)
print(f"NADB Wiki System initialized with Redis at {redis_host}:{redis_port} (DB: {redis_db})")

# Configurar Markdown
md = markdown.Markdown(extensions=['codehilite', 'fenced_code', 'tables', 'toc'])

# Adicionar filtro Markdown ao Jinja2
@app.template_filter('markdown')
def markdown_filter(text):
    return Markup(md.convert(text))

class WikiSystem:
    def __init__(self, kv_store):
        self.kv = kv_store
    
    def get_page_key(self, slug):
        """Generate NADB key for a wiki page."""
        return f"page:{slug}"
    
    def get_version_key(self, slug, version):
        """Generate NADB key for a specific page version."""
        return f"page:{slug}:v{version}"
    
    def get_stats_key(self):
        """Generate NADB key for wiki statistics."""
        return "wiki:stats"
    
    def create_page(self, slug, title, content, author='anonymous', tags=None):
        """Criar nova página ou nova versão"""
        if tags is None:
            tags = []
        
        page_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        # Obter versão atual
        current_page = self.get_page(slug)
        version = (current_page['version'] + 1) if current_page else 1
        
        page_data = {
            'id': page_id,
            'slug': slug,
            'title': title,
            'content': content,
            'author': author,
            'created_at': timestamp,
            'version': version,
            'tags': tags,
            'views': current_page['views'] if current_page else 0,
            'last_modified': timestamp
        }
        
        # Tags para indexação NADB
        nadb_tags = [
            'wiki_page',
            f'slug:{slug}',
            f'author:{author}',
            f'version:{version}',
            'current'  # Marca como versão atual
        ] + [f'tag:{tag}' for tag in tags]
        
        try:
            # Archive previous version if exists
            if current_page:
                old_tags = ['wiki_page', f'slug:{slug}', f'author:{current_page["author"]}', 
                           f'version:{current_page["version"]}', 'archived']
                old_tags.extend([f'tag:{tag}' for tag in current_page.get('tags', [])])
                
                version_key = self.get_version_key(slug, current_page['version'])
                self.kv.set(version_key, json.dumps(current_page).encode('utf-8'), tags=old_tags)
            
            # Save new version as current
            current_key = self.get_page_key(slug)
            version_key = self.get_version_key(slug, version)
            
            page_json = json.dumps(page_data).encode('utf-8')
            self.kv.set(current_key, page_json, tags=nadb_tags)
            self.kv.set(version_key, page_json, tags=nadb_tags)
            
            # Update statistics
            self._update_stats('pages_created')
            
            print(f"Created/updated wiki page: {slug} (v{version})")
            return page_data
            
        except Exception as e:
            print(f"Error creating page {slug}: {e}")
            raise
    
    def get_page(self, slug):
        """Obter página atual por slug"""
        try:
            key = self.get_page_key(slug)
            page_data = self.kv.get(key)
            return json.loads(page_data.decode('utf-8'))
        except KeyError:
            return None
        except Exception as e:
            print(f"Error getting page {slug}: {e}")
            return None
    
    def get_page_version(self, slug, version):
        """Obter versão específica de uma página"""
        try:
            key = self.get_version_key(slug, version)
            page_data = self.kv.get(key)
            return json.loads(page_data.decode('utf-8'))
        except KeyError:
            return None
        except Exception as e:
            print(f"Error getting page version {slug}:v{version}: {e}")
            return None
    
    def get_page_history(self, slug):
        """Obter histórico de versões de uma página"""
        try:
            # Query all versions of this page
            results = self.kv.query_by_tags(['wiki_page', f'slug:{slug}'])
            versions = []
            
            for key, metadata in results.items():
                if ':v' in key:  # Only version keys
                    try:
                        page_data = self.kv.get(key)
                        page_dict = json.loads(page_data.decode('utf-8'))
                        versions.append(page_dict)
                    except Exception as e:
                        print(f"Error loading version {key}: {e}")
                        continue
            
            return sorted(versions, key=lambda x: x['version'], reverse=True)
        except Exception as e:
            print(f"Error getting page history for {slug}: {e}")
            return []
    
    def increment_views(self, slug):
        """Incrementar contador de visualizações"""
        page = self.get_page(slug)
        if page:
            page['views'] += 1
            page['last_viewed'] = datetime.now().isoformat()
            
            # Prepare tags for NADB
            nadb_tags = [
                'wiki_page',
                f'slug:{slug}',
                f'author:{page["author"]}',
                f'version:{page["version"]}',
                'current'
            ] + [f'tag:{tag}' for tag in page.get('tags', [])]
            
            try:
                # Update current page with new view count
                key = self.get_page_key(slug)
                page_json = json.dumps(page).encode('utf-8')
                self.kv.set(key, page_json, tags=nadb_tags)
                
                # Update global statistics
                self._update_stats('total_views')
                    
            except Exception as e:
                print(f"Error incrementing views for {slug}: {e}")
    
    def search_pages(self, query, tags=None):
        """Buscar páginas por conteúdo e tags"""
        if tags is None:
            tags = []
        
        search_tags = ['wiki_page', 'current']
        if tags:
            search_tags.extend([f'tag:{tag}' for tag in tags])
        
        try:
            results = self.kv.query_by_tags(search_tags)
            pages = []
            
            for key, metadata in results.items():
                try:
                    page_data = self.kv.get(key)
                    page_dict = json.loads(page_data.decode('utf-8'))
                    
                    # Busca textual simples
                    if query:
                        content_lower = page_dict['content'].lower()
                        title_lower = page_dict['title'].lower()
                        query_lower = query.lower()
                        
                        if query_lower in content_lower or query_lower in title_lower:
                            # Calcular relevância
                            title_matches = title_lower.count(query_lower) * 3
                            content_matches = content_lower.count(query_lower)
                            page_dict['relevance'] = title_matches + content_matches
                            pages.append(page_dict)
                    else:
                        pages.append(page_dict)
                except Exception as e:
                    print(f"Error processing search result {key}: {e}")
                    continue
            
            # Ordenar por relevância se houver busca textual
            if query:
                pages.sort(key=lambda x: x.get('relevance', 0), reverse=True)
            else:
                pages.sort(key=lambda x: x.get('views', 0), reverse=True)
            
            return pages
            
        except Exception as e:
            print(f"Error searching pages: {e}")
            return []
    
    def get_popular_pages(self, limit=10):
        """Obter páginas mais populares"""
        try:
            results = self.kv.query_by_tags(['wiki_page', 'current'])
            pages = []
            
            for key, metadata in results.items():
                try:
                    page_data = self.kv.get(key)
                    page_dict = json.loads(page_data.decode('utf-8'))
                    pages.append(page_dict)
                except Exception as e:
                    print(f"Error loading popular page {key}: {e}")
                    continue
            
            return sorted(pages, key=lambda x: x.get('views', 0), reverse=True)[:limit]
            
        except Exception as e:
            print(f"Error getting popular pages: {e}")
            return []
    
    def get_recent_pages(self, limit=10):
        """Obter páginas recentes"""
        try:
            results = self.kv.query_by_tags(['wiki_page', 'current'])
            pages = []
            
            for key, metadata in results.items():
                try:
                    page_data = self.kv.get(key)
                    page_dict = json.loads(page_data.decode('utf-8'))
                    pages.append(page_dict)
                except Exception as e:
                    print(f"Error loading recent page {key}: {e}")
                    continue
            
            return sorted(pages, key=lambda x: x.get('last_modified', ''), reverse=True)[:limit]
            
        except Exception as e:
            print(f"Error getting recent pages: {e}")
            return []
    
    def get_all_tags(self):
        """Obter todas as tags utilizadas"""
        try:
            results = self.kv.query_by_tags(['wiki_page', 'current'])
            all_tags = []
            
            for key, metadata in results.items():
                try:
                    page_data = self.kv.get(key)
                    page_dict = json.loads(page_data.decode('utf-8'))
                    all_tags.extend(page_dict.get('tags', []))
                except Exception as e:
                    print(f"Error loading tags from {key}: {e}")
                    continue
            
            return Counter(all_tags).most_common()
            
        except Exception as e:
            print(f"Error getting all tags: {e}")
            return []
    
    def get_stats(self):
        """Obter estatísticas do wiki"""
        try:
            stats_key = self.get_stats_key()
            stats_data = self.kv.get(stats_key)
            stats = json.loads(stats_data.decode('utf-8'))
        except KeyError:
            stats = {}
        except Exception as e:
            print(f"Error getting stats: {e}")
            stats = {}
        
        # Calcular estatísticas em tempo real
        try:
            current_pages = self.kv.query_by_tags(['wiki_page', 'current'])
            total_pages = len(current_pages)
            
            total_views = 0
            for key, metadata in current_pages.items():
                try:
                    page_data = self.kv.get(key)
                    page_dict = json.loads(page_data.decode('utf-8'))
                    total_views += page_dict.get('views', 0)
                except Exception as e:
                    print(f"Error calculating views for {key}: {e}")
                    continue
            
            stats.update({
                'total_pages': total_pages,
                'total_views': total_views,
                'pages_created_today': stats.get('pages_created_today', 0),
                'last_updated': datetime.now().isoformat()
            })
            
        except Exception as e:
            print(f"Error calculating real-time stats: {e}")
        
        return stats
    
    def _update_stats(self, metric):
        """Atualizar estatísticas"""
        try:
            stats_key = self.get_stats_key()
            stats_data = self.kv.get(stats_key)
            stats = json.loads(stats_data.decode('utf-8'))
        except KeyError:
            stats = {}
        except Exception as e:
            print(f"Error getting stats for update: {e}")
            stats = {}
        
        stats[metric] = stats.get(metric, 0) + 1
        stats['last_updated'] = datetime.now().isoformat()
        
        stats_json = json.dumps(stats).encode('utf-8')
        self.kv.set(stats_key, stats_json, tags=['wiki_stats'])

# Instanciar sistema
wiki = WikiSystem(kv_store)

@app.route('/')
def home():
    """Página inicial com estatísticas"""
    stats = wiki.get_stats()
    popular_pages = wiki.get_popular_pages(5)
    recent_pages = wiki.get_recent_pages(5)
    all_tags = wiki.get_all_tags()[:10]  # Top 10 tags
    
    # Incrementar visualizações da home
    wiki.increment_views('home')
    home_page = wiki.get_page('home')
    
    return render_template('wiki.html', 
                         page=home_page,
                         stats=stats,
                         popular_pages=popular_pages,
                         recent_pages=recent_pages,
                         all_tags=all_tags,
                         is_home=True)

@app.route('/page/<slug>')
def view_page(slug):
    """Visualizar página específica"""
    page = wiki.get_page(slug)
    if not page:
        return render_template('wiki.html', 
                             page=None, 
                             error=f"Página '{slug}' não encontrada")
    
    # Incrementar visualizações
    wiki.increment_views(slug)
    
    # Obter dados para sidebar
    stats = wiki.get_stats()
    popular_pages = wiki.get_popular_pages(5)
    recent_pages = wiki.get_recent_pages(5)
    all_tags = wiki.get_all_tags()[:10]
    
    return render_template('wiki.html', 
                         page=page,
                         stats=stats,
                         popular_pages=popular_pages,
                         recent_pages=recent_pages,
                         all_tags=all_tags)

@app.route('/create')
def create_page():
    """Formulário para criar nova página"""
    stats = wiki.get_stats()
    popular_pages = wiki.get_popular_pages(5)
    recent_pages = wiki.get_recent_pages(5)
    all_tags = wiki.get_all_tags()[:10]
    
    return render_template('wiki.html', 
                         create_mode=True,
                         stats=stats,
                         popular_pages=popular_pages,
                         recent_pages=recent_pages,
                         all_tags=all_tags)

@app.route('/edit/<slug>')
def edit_page(slug):
    """Formulário para editar página"""
    page = wiki.get_page(slug)
    if not page:
        return redirect(url_for('home'))
    
    stats = wiki.get_stats()
    popular_pages = wiki.get_popular_pages(5)
    recent_pages = wiki.get_recent_pages(5)
    all_tags = wiki.get_all_tags()[:10]
    
    return render_template('wiki.html', 
                         page=page,
                         edit_mode=True,
                         stats=stats,
                         popular_pages=popular_pages,
                         recent_pages=recent_pages,
                         all_tags=all_tags)

@app.route('/history/<slug>')
def page_history(slug):
    """Histórico de versões da página"""
    history = wiki.get_page_history(slug)
    current_page = wiki.get_page(slug)
    
    stats = wiki.get_stats()
    popular_pages = wiki.get_popular_pages(5)
    recent_pages = wiki.get_recent_pages(5)
    all_tags = wiki.get_all_tags()[:10]
    
    return render_template('wiki.html', 
                         page=current_page,
                         history=history,
                         stats=stats,
                         popular_pages=popular_pages,
                         recent_pages=recent_pages,
                         all_tags=all_tags)

@app.route('/search')
def search():
    """Buscar páginas"""
    query = request.args.get('q', '')
    tag_filter = request.args.get('tag', '')
    
    tags = [tag_filter] if tag_filter else []
    results = wiki.search_pages(query, tags)
    
    stats = wiki.get_stats()
    popular_pages = wiki.get_popular_pages(5)
    recent_pages = wiki.get_recent_pages(5)
    all_tags = wiki.get_all_tags()[:10]
    
    return render_template('wiki.html', 
                         search_results=results,
                         search_query=query,
                         search_tag=tag_filter,
                         stats=stats,
                         popular_pages=popular_pages,
                         recent_pages=recent_pages,
                         all_tags=all_tags)

# API Endpoints
@app.route('/api/save', methods=['POST'])
def api_save_page():
    """API para salvar página"""
    data = request.get_json()
    
    slug = data.get('slug', '').strip()
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    tags = [tag.strip() for tag in data.get('tags', '').split(',') if tag.strip()]
    author = session.get('author', 'anonymous')
    
    if not slug or not title or not content:
        return jsonify({'error': 'Slug, título e conteúdo são obrigatórios'}), 400
    
    # Validar slug
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        return jsonify({'error': 'Slug deve conter apenas letras, números, _ e -'}), 400
    
    try:
        page = wiki.create_page(slug, title, content, author, tags)
        return jsonify({'success': True, 'page': page})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/preview', methods=['POST'])
def api_preview():
    """API para preview de Markdown"""
    data = request.get_json()
    content = data.get('content', '')
    
    try:
        html = md.convert(content)
        return jsonify({'html': html})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def api_stats():
    """API para estatísticas em tempo real"""
    return jsonify(wiki.get_stats())

if __name__ == '__main__':
    print("🚀 Iniciando Wiki System...")
    print("📊 Dashboard: http://localhost:5000")
    print("📝 Criar página: http://localhost:5000/create")
    print("🔍 Buscar: http://localhost:5000/search")
    
    app.run(debug=True, host='0.0.0.0', port=5000)