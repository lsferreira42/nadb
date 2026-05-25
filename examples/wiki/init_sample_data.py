#!/usr/bin/env python3
"""
Inicializar dados de exemplo para o Wiki System
Cria páginas de exemplo demonstrando as funcionalidades do NADB
"""

import os
import sys
import json
from datetime import datetime

# Adicionar o diretório pai ao path para importar NADB
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from wiki_system import WikiSystem, kv_store

def init_sample_data():
    """Inicializar páginas de exemplo no wiki"""
    
    wiki = WikiSystem(kv_store)
    
    print("🚀 Inicializando dados de exemplo para o Wiki System...")
    
    # Verificar se já existem páginas
    existing_pages = wiki.get_popular_pages(limit=1)
    if existing_pages:
        print("⚠️  Páginas já existem no wiki. Deseja continuar? (y/N)")
        response = input().strip().lower()
        if response != 'y':
            print("❌ Cancelado.")
            return
    
    # 1. Página inicial
    print("📝 Criando página inicial...")
    wiki.create_page(
        slug='home',
        title='Wiki Home - Sistema de Documentação NADB',
        content="""# 🏠 Bem-vindo ao Wiki System

Este é um **sistema de wiki completo** construído com **NADB** como backend de persistência, demonstrando todas as funcionalidades avançadas de um banco de dados moderno.

## 🚀 Funcionalidades Implementadas

### 📚 Gestão de Conteúdo
- ✅ **Versionamento completo** de artigos com histórico
- ✅ **Editor Markdown** com preview em tempo real
- ✅ **Sistema de tags** para categorização
- ✅ **Busca avançada** por conteúdo e tags

### 📊 Analytics & Estatísticas
- ✅ **Contadores de visualizações** por página
- ✅ **Páginas mais populares** em tempo real
- ✅ **Artigos recentes** ordenados por data
- ✅ **Estatísticas globais** do wiki

### 🔧 Funcionalidades NADB
- ✅ **Transações ACID** para consistência de dados
- ✅ **Indexação inteligente** com tags
- ✅ **Cache automático** para performance
- ✅ **Backup & Recovery** integrado

## 📖 Páginas de Exemplo

Explore as páginas de exemplo criadas para demonstrar as funcionalidades:

- **[Guia NADB](/page/nadb-guide)** - Tutorial completo sobre NADB
- **[Markdown Showcase](/page/markdown-showcase)** - Demonstração de formatação
- **[Versionamento](/page/versioning-demo)** - Como funciona o controle de versões
- **[Performance](/page/performance-tips)** - Dicas de otimização

## 🎯 Como Usar

1. **📝 Criar**: Clique em "Nova Página" para criar um artigo
2. **✏️ Editar**: Clique no ícone de edição em qualquer página
3. **🔍 Buscar**: Use a barra de busca para encontrar conteúdo
4. **🏷️ Navegar**: Explore as tags e categorias
5. **📈 Estatísticas**: Veja métricas em tempo real na sidebar

## 🛠️ Tecnologias

- **Backend**: NADB (Next-generation Key-Value Store)
- **Storage**: Redis para alta performance
- **Frontend**: Flask + HTML5 + CSS3 + JavaScript
- **Markdown**: Renderização em tempo real
- **Transações**: ACID compliance para consistência

---
*Powered by **NADB** - O futuro dos bancos de dados key-value! 🚀*
""",
        author='system',
        tags=['home', 'welcome', 'documentation', 'nadb']
    )
    
    # 2. Guia completo do NADB
    print("📖 Criando guia do NADB...")
    wiki.create_page(
        slug='nadb-guide',
        title='Guia Completo do NADB',
        content="""# 📚 Guia Completo do NADB

**NADB** (Not A Database) é um sistema de armazenamento key-value de alta performance com funcionalidades avançadas que rivalizam com bancos de dados tradicionais.

## 🎯 O que é NADB?

NADB é mais que um simples key-value store. É uma solução completa que oferece:

### 🔥 Funcionalidades Core
- **Key-Value Storage**: Armazenamento rápido e eficiente
- **Multiple Backends**: Redis, FileSystem, e mais
- **ACID Transactions**: Consistência garantida
- **Intelligent Indexing**: Busca rápida por tags
- **Automatic Caching**: Performance otimizada

### 🚀 Funcionalidades Avançadas
- **Backup & Recovery**: Sistema de backup integrado
- **Structured Logging**: Logs JSON estruturados
- **Connection Pooling**: Otimização para alta concorrência
- **Namespace Support**: Organização lógica de dados

## 💻 Exemplo de Uso

```python
from nadb import KeyValueStore
import os

# Inicializar NADB
storage_engine = os.environ.get("NADB_STORAGE_ENGINE", "fs")
kv_store = KeyValueStore(
    data_folder_path='./data',
    db='my_app',
    namespace='users',
    storage_backend=storage_engine,
    storage_options={"host": "localhost", "port": 6379, "db": 0} if storage_engine == "redis" else None,
    enable_transactions=True,
    enable_backup=True,
    enable_indexing=True
)

# Salvar dados com tags
user_data = {"name": "João", "email": "joao@email.com"}
kv_store.set_json("user:123", user_data, tags=["user", "active", "premium"])

# Buscar por tags
results = kv_store.query_by_tags(["user", "premium"])
```

## 🏷️ Sistema de Tags

As tags são fundamentais no NADB para:

- **Indexação**: Busca rápida por categorias
- **Organização**: Agrupamento lógico de dados
- **Filtragem**: Consultas específicas
- **Analytics**: Métricas por categoria

### Exemplo de Tags no Wiki:
```python
# Tags para uma página wiki
tags = [
    'wiki_page',        # Tipo de conteúdo
    'slug:nadb-guide',  # Identificador único
    'author:system',    # Autor
    'tag:tutorial',     # Categoria
    'tag:nadb',         # Tópico
    'current'           # Status
]
```

## 🔄 Transações ACID

NADB suporta transações completas:

```python
with kv_store.transaction() as tx:
    # Operações atômicas
    tx.set("counter", new_value, tags=["counter"])
    tx.set("log", log_entry, tags=["log", "today"])
    # Commit automático ou rollback em caso de erro
```

## 📊 Backup & Recovery

Sistema de backup integrado:

```python
# Criar backup
backup_meta = kv_store.create_backup(
    "wiki_backup_20241006", 
    compression=True
)

# Restaurar backup
kv_store.restore_backup("wiki_backup_20241006")
```

## 🎯 Casos de Uso Ideais

- **Aplicações Web**: Cache e sessões
- **Analytics**: Métricas em tempo real
- **CMS**: Sistemas de conteúdo
- **E-commerce**: Carrinho e produtos
- **IoT**: Dados de sensores
- **Gaming**: Estados de jogo

## 🔗 Links Úteis

- [GitHub Repository](https://github.com/lsferreira42/nadb)
- [Documentação Completa](/page/documentation)
- [Exemplos Práticos](/page/examples)
- [Performance Tips](/page/performance-tips)

---
*NADB: Simplicidade de key-value com poder de banco de dados! 💪*
""",
        author='nadb-team',
        tags=['nadb', 'tutorial', 'documentation', 'guide', 'database']
    )
    
    # 3. Showcase de Markdown
    print("🎨 Criando showcase de Markdown...")
    wiki.create_page(
        slug='markdown-showcase',
        title='Markdown Showcase - Formatação Completa',
        content="""# 🎨 Markdown Showcase

Esta página demonstra todas as funcionalidades de **Markdown** suportadas pelo Wiki System.

## 📝 Formatação de Texto

### Básico
- **Negrito** com `**texto**`
- *Itálico* com `*texto*`
- ~~Riscado~~ com `~~texto~~`
- `Código inline` com backticks

### Combinações
- ***Negrito e itálico*** com `***texto***`
- **Negrito com `código`** misturado
- *Itálico com [link](https://example.com)*

## 📋 Listas

### Lista não ordenada
- Item 1
- Item 2
  - Subitem 2.1
  - Subitem 2.2
    - Sub-subitem 2.2.1
- Item 3

### Lista ordenada
1. Primeiro item
2. Segundo item
   1. Subitem numerado
   2. Outro subitem
3. Terceiro item

### Lista de tarefas
- [x] Tarefa concluída
- [x] Outra tarefa feita
- [ ] Tarefa pendente
- [ ] Mais uma pendente

## 💻 Código

### Código inline
Use `kv_store.get_json(key)`, `kv_store.get_text(key)` ou `kv_store.get_bytes(key)` para obter dados no tipo esperado.

### Bloco de código simples
```
def hello_world():
    print("Hello, World!")
```

### Código Python com syntax highlighting
```python
from nadb import KeyValueStore
import os

# Inicializar NADB
storage_engine = os.environ.get("NADB_STORAGE_ENGINE", "fs")
kv_store = KeyValueStore(
    data_folder_path='./data',
    db='wiki',
    namespace='pages',
    storage_backend=storage_engine,
    storage_options={"host": "localhost", "port": 6379, "db": 3} if storage_engine == "redis" else None
)

# Salvar página
page_data = {
    'title': 'Minha Página',
    'content': 'Conteúdo da página...',
    'tags': ['wiki', 'exemplo']
}

kv_store.set_json('page:exemplo', page_data, tags=['wiki_page', 'exemplo'])
```

### Código JavaScript
```javascript
// Função para preview de Markdown
function updatePreview() {
    const content = document.getElementById('content').value;
    
    fetch('/api/preview', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content: content })
    })
    .then(response => response.json())
    .then(data => {
        document.getElementById('preview').innerHTML = data.html;
    });
}
```

## 📊 Tabelas

| Funcionalidade | NADB | Redis | MongoDB |
|----------------|------|-------|---------|
| Key-Value      | ✅   | ✅    | ❌      |
| Transações     | ✅   | ⚠️    | ✅      |
| Tags/Indexing  | ✅   | ❌    | ✅      |
| Backup         | ✅   | ⚠️    | ✅      |
| Performance    | 🚀   | 🚀    | ⚡      |

## 🔗 Links

- [Link simples](https://nadb.dev)
- [Link com título](https://nadb.dev "NADB Official")
- [Link interno](/page/nadb-guide)
- [Link para seção](#código)

## 📷 Imagens

![NADB Logo](https://via.placeholder.com/400x200/4361ee/ffffff?text=NADB)

*Legenda: Logo conceitual do NADB*

## 📝 Citações

> NADB não é apenas um banco de dados,  
> é uma revolução na forma como armazenamos dados.
> 
> — Equipe NADB

### Citação aninhada
> Esta é uma citação principal.
> 
> > Esta é uma citação aninhada.
> > Pode ter múltiplas linhas.
> 
> Voltando à citação principal.

## ⚠️ Alertas e Destaques

### Informação
> ℹ️ **Dica**: Use tags consistentes para melhor organização.

### Aviso
> ⚠️ **Atenção**: Sempre faça backup antes de atualizações importantes.

### Erro
> ❌ **Erro**: Não misture JSON manual com `get()`: prefira `set_json()` e `get_json()`.

### Sucesso
> ✅ **Sucesso**: NADB configurado corretamente!

## 🔢 Fórmulas e Símbolos

Símbolos especiais: α β γ δ ε ζ η θ ι κ λ μ ν ξ ο π ρ σ τ υ φ χ ψ ω

Setas: → ← ↑ ↓ ↔ ⇒ ⇐ ⇑ ⇓ ⇔

Matemática: ∑ ∏ ∫ ∂ ∇ ∞ ± × ÷ ≠ ≤ ≥ ≈ ∝

## 📋 Linha Horizontal

Acima da linha.

---

Abaixo da linha.

## 🎯 Conclusão

Este showcase demonstra a **versatilidade** e **poder** do Markdown no Wiki System. 

Com NADB como backend, temos:
1. **Performance** excepcional
2. **Flexibilidade** total
3. **Confiabilidade** garantida

*Experimente criar suas próprias páginas!* 🚀
""",
        author='wiki-admin',
        tags=['markdown', 'showcase', 'formatting', 'examples', 'tutorial']
    )
    
    # 4. Demo de versionamento
    print("🔄 Criando demo de versionamento...")
    wiki.create_page(
        slug='versioning-demo',
        title='Demonstração de Versionamento',
        content="""# 🔄 Sistema de Versionamento do Wiki

Esta página demonstra como o **versionamento** funciona no Wiki System usando NADB.

## 📚 O que é Versionamento?

Versionamento é a capacidade de manter um **histórico completo** de todas as alterações feitas em uma página, permitindo:

- 📖 **Visualizar** versões anteriores
- 🔄 **Comparar** mudanças entre versões  
- ⏪ **Reverter** para versões anteriores
- 👥 **Rastrear** quem fez cada alteração

## 🛠️ Como Funciona no NADB

### Estrutura de Chaves
```
page:versioning-demo        # Versão atual
page:versioning-demo:v1     # Versão 1
page:versioning-demo:v2     # Versão 2
page:versioning-demo:v3     # Versão 3 (atual)
```

### Tags de Versionamento
```python
# Versão atual
tags = ['wiki_page', 'slug:versioning-demo', 'current', 'version:3']

# Versão arquivada
tags = ['wiki_page', 'slug:versioning-demo', 'archived', 'version:2']
```

## 📊 Metadados de Versão

Cada versão mantém:
- **ID único** da versão
- **Timestamp** de criação
- **Autor** da alteração
- **Número da versão**
- **Tags** associadas

## 🔍 Exemplo Prático

Esta é a **versão inicial** desta página. Nas próximas edições, você poderá:

1. Ver o histórico completo
2. Comparar as diferenças
3. Entender como o conteúdo evoluiu

## 🎯 Benefícios

### Para Usuários
- ✅ **Segurança**: Nunca perca conteúdo
- ✅ **Colaboração**: Veja quem mudou o quê
- ✅ **Auditoria**: Histórico completo de mudanças

### Para Desenvolvedores
- ✅ **ACID**: Transações garantem consistência
- ✅ **Performance**: Indexação inteligente por tags
- ✅ **Escalabilidade**: Redis backend de alta performance

## 🚀 Próximos Passos

1. **Edite** esta página para criar uma nova versão
2. **Visualize** o histórico na aba "Histórico"
3. **Compare** as diferenças entre versões
4. **Experimente** reverter para uma versão anterior

---
*Esta é a versão 1 desta página. Edite para ver o versionamento em ação!*
""",
        author='demo-user',
        tags=['versioning', 'demo', 'tutorial', 'nadb', 'wiki']
    )
    
    # 5. Dicas de performance
    print("⚡ Criando dicas de performance...")
    wiki.create_page(
        slug='performance-tips',
        title='Dicas de Performance e Otimização',
        content="""# ⚡ Performance e Otimização no NADB

Guia completo para **maximizar a performance** do seu sistema usando NADB.

## 🎯 Princípios Fundamentais

### 1. 🏷️ Use Tags Inteligentemente
```python
# ❌ Tags muito genéricas
tags = ['data', 'info']

# ✅ Tags específicas e hierárquicas
tags = ['wiki_page', 'category:tutorial', 'author:admin', 'status:published']
```

### 2. 🔄 Aproveite o Cache
```python
# Cache automático do NADB
kv_store = KeyValueStore(
    cache_size=1000,  # Cache até 1000 consultas
    enable_indexing=True  # Indexação inteligente
)
```

### 3. 📦 Use Transações para Operações Relacionadas
```python
# ✅ Operações atômicas
with kv_store.transaction() as tx:
    tx.set('user:123', user_data, tags=['user', 'active'])
    tx.set('profile:123', profile_data, tags=['profile', 'user:123'])
    tx.set('stats:users', updated_stats, tags=['stats'])
```

## 🚀 Otimizações Específicas

### Redis Backend
```python
import os

storage_engine = os.environ.get("NADB_STORAGE_ENGINE", "fs")
kv_store = KeyValueStore(
    data_folder_path='./data',
    db='wiki',
    namespace='pages',
    storage_backend=storage_engine,
    storage_options={
        'host': 'localhost',
        'port': 6379,
        'db': 0,
        'max_connections': 20,  # Pool de conexões
        'socket_keepalive': True,
        'socket_keepalive_options': {}
    } if storage_engine == "redis" else None
)
```

### Consultas Eficientes
```python
# ❌ Consulta muito ampla
results = kv_store.query_by_tags(['data'])

# ✅ Consulta específica
results = kv_store.query_by_tags(['wiki_page', 'category:tutorial', 'published'])
```

## 📊 Monitoramento

### Estatísticas do NADB
```python
stats = kv_store.get_stats()
print(f"Cache hits: {stats.get('cache_hits', 0)}")
print(f"Total queries: {stats.get('total_queries', 0)}")
print(f"Average response time: {stats.get('avg_response_time', 0)}ms")
```

### Métricas Importantes
- **Cache Hit Rate**: > 80% é ideal
- **Query Response Time**: < 10ms para consultas simples
- **Transaction Success Rate**: > 99.9%
- **Memory Usage**: Monitorar crescimento

## 🔧 Configurações Recomendadas

### Para Aplicações Web
```python
kv_store = KeyValueStore(
    data_folder_path='./data',
    db='web_app',
    namespace='cache',
    buffer_size_mb=5,        # Buffer maior para writes
    cache_size=2000,         # Cache extenso
    enable_indexing=True,    # Indexação ativa
    enable_transactions=True # Consistência garantida
)
```

### Para Analytics
```python
kv_store = KeyValueStore(
    data_folder_path='./data',
    db='analytics',
    namespace='events',
    buffer_size_mb=10,       # Buffer grande para bulk writes
    cache_size=5000,         # Cache muito extenso
    enable_indexing=True,    # Consultas rápidas por tags
    cache_ttl_seconds=1      # Cache curto para dados recentes
)
```

### Para IoT/High Throughput
```python
kv_store = KeyValueStore(
    data_folder_path='./data',
    db='iot',
    namespace='telemetry',
    buffer_size_mb=20,       # Buffer máximo
    cache_size=1000,         # Cache moderado
    enable_indexing=False    # Menos overhead
)
```

## 📈 Benchmarks

### Operações por Segundo (Redis Backend)
- **SET**: ~100,000 ops/sec
- **GET**: ~150,000 ops/sec  
- **Query by Tags**: ~50,000 ops/sec
- **Transactions**: ~80,000 ops/sec

### Latência Média
- **GET simples**: < 1ms
- **SET com tags**: < 2ms
- **Query complexa**: < 5ms
- **Transação**: < 3ms

## 🎯 Casos de Uso Otimizados

### 1. Sistema de Cache Web
```python
# Cache de sessões
session_tags = ['session', f'user:{user_id}', 'active']
kv_store.set_json(f'session:{session_id}', session_data, tags=session_tags)

# Cache de páginas
page_tags = ['cache', 'page', f'url:{url_hash}', 'valid']
kv_store.set_text(f'page_cache:{url_hash}', html_content, tags=page_tags)
```

### 2. Analytics em Tempo Real
```python
# Métricas por minuto
metric_tags = ['metric', 'pageview', f'date:{today}', f'hour:{hour}']
kv_store.set_json(f'metric:{timestamp}', metric_data, tags=metric_tags)

# Agregações rápidas
hourly_metrics = kv_store.query_by_tags(['metric', 'pageview', f'hour:{hour}'])
```

### 3. E-commerce
```python
# Produtos com múltiplas dimensões
product_tags = [
    'product', 
    f'category:{category}', 
    f'brand:{brand}',
    f'price_range:{price_range}',
    'in_stock'
]
kv_store.set_json(f'product:{product_id}', product_data, tags=product_tags)
```

## ⚠️ Armadilhas Comuns

### 1. Tags Demais
```python
# ❌ Muitas tags desnecessárias
tags = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j']

# ✅ Tags focadas e úteis
tags = ['product', 'category:electronics', 'brand:apple', 'in_stock']
```

### 2. Consultas Ineficientes
```python
# ❌ Consulta muito ampla
all_data = kv_store.query_by_tags(['data'])

# ✅ Consulta específica com paginação
recent_posts = kv_store.query_by_tags_advanced(
    tags=['blog_post', 'published'],
    page=1,
    page_size=20
)
```

### 3. Transações Desnecessárias
```python
# ❌ Transação para operação simples
with kv_store.transaction() as tx:
    tx.set('simple_key', simple_value)

# ✅ SET tipado direto para operações simples
kv_store.set_text('simple_key', simple_value, tags=['simple'])
```

## 🔍 Debugging e Profiling

### Logs Estruturados
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# NADB automaticamente loga operações em JSON
# Analise os logs para identificar gargalos
```

### Ferramentas de Monitoramento
- **Redis Monitor**: `redis-cli monitor`
- **NADB Stats**: `kv_store.get_stats()`
- **System Metrics**: CPU, Memory, Disk I/O

## 🎉 Conclusão

Com essas otimizações, seu sistema NADB pode atingir:
- **Alta performance** (>100k ops/sec)
- **Baixa latência** (<5ms)
- **Alta disponibilidade** (>99.9%)
- **Escalabilidade** horizontal

*Performance é uma jornada, não um destino!* 🚀
""",
        author='performance-team',
        tags=['performance', 'optimization', 'tutorial', 'nadb', 'redis', 'advanced']
    )
    
    # Criar algumas versões adicionais da página de versionamento para demonstrar o histórico
    print("📝 Criando versões adicionais para demonstrar versionamento...")
    
    # Versão 2
    wiki.create_page(
        slug='versioning-demo',
        title='Demonstração de Versionamento - Atualizada',
        content="""# 🔄 Sistema de Versionamento do Wiki (v2)

Esta página demonstra como o **versionamento** funciona no Wiki System usando NADB.

## 📚 O que é Versionamento?

Versionamento é a capacidade de manter um **histórico completo** de todas as alterações feitas em uma página, permitindo:

- 📖 **Visualizar** versões anteriores
- 🔄 **Comparar** mudanças entre versões  
- ⏪ **Reverter** para versões anteriores
- 👥 **Rastrear** quem fez cada alteração

## 🛠️ Como Funciona no NADB

### Estrutura de Chaves
```
page:versioning-demo        # Versão atual
page:versioning-demo:v1     # Versão 1
page:versioning-demo:v2     # Versão 2 (atual)
```

### Tags de Versionamento
```python
# Versão atual
tags = ['wiki_page', 'slug:versioning-demo', 'current', 'version:2']

# Versão arquivada
tags = ['wiki_page', 'slug:versioning-demo', 'archived', 'version:1']
```

## 📊 Metadados de Versão

Cada versão mantém:
- **ID único** da versão
- **Timestamp** de criação
- **Autor** da alteração
- **Número da versão**
- **Tags** associadas

## 🔍 Exemplo Prático - ATUALIZADO!

Esta é agora a **segunda versão** desta página! Você pode ver que:

1. O conteúdo foi modificado
2. Uma nova versão foi criada automaticamente
3. A versão anterior foi preservada
4. O histórico está disponível

## 🎯 Benefícios

### Para Usuários
- ✅ **Segurança**: Nunca perca conteúdo
- ✅ **Colaboração**: Veja quem mudou o quê
- ✅ **Auditoria**: Histórico completo de mudanças
- ✅ **Flexibilidade**: Reverta mudanças facilmente

### Para Desenvolvedores
- ✅ **ACID**: Transações garantem consistência
- ✅ **Performance**: Indexação inteligente por tags
- ✅ **Escalabilidade**: Redis backend de alta performance
- ✅ **Simplicidade**: API intuitiva para versionamento

## 🚀 Próximos Passos

1. **Edite** esta página novamente para criar a versão 3
2. **Visualize** o histórico na aba "Histórico"
3. **Compare** as diferenças entre as 3 versões
4. **Experimente** reverter para uma versão anterior

---
*Esta é a versão 2 desta página. Continue editando para ver mais versões!*
""",
        author='demo-user-2',
        tags=['versioning', 'demo', 'tutorial', 'nadb', 'wiki', 'updated']
    )
    
    print("✅ Dados de exemplo criados com sucesso!")
    print("\n📊 Resumo:")
    
    # Mostrar estatísticas
    stats = wiki.get_stats()
    print(f"   📄 Total de páginas: {stats.get('total_pages', 0)}")
    print(f"   👀 Total de visualizações: {stats.get('total_views', 0)}")
    
    # Mostrar páginas criadas
    pages = wiki.get_recent_pages(10)
    print(f"\n📝 Páginas criadas:")
    for page in pages:
        print(f"   • {page['title']} (/{page['slug']})")
    
    # Mostrar tags
    tags = wiki.get_all_tags()
    print(f"\n🏷️  Tags disponíveis:")
    for tag, count in tags[:10]:
        print(f"   • {tag} ({count})")
    
    print(f"\n🚀 Wiki System pronto!")
    print(f"   🌐 Acesse: http://localhost:5000")
    print(f"   📝 Criar página: http://localhost:5000/create")
    print(f"   🔍 Buscar: http://localhost:5000/search")

if __name__ == '__main__':
    try:
        init_sample_data()
    except KeyboardInterrupt:
        print("\n❌ Cancelado pelo usuário.")
    except Exception as e:
        print(f"❌ Erro ao inicializar dados: {e}")
        import traceback
        traceback.print_exc()
