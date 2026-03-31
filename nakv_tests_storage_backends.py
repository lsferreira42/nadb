import pytest
import os
import tempfile
import time
import json
import uuid
import shutil
from datetime import datetime, timedelta

# Importar Redis - sem tratamento de erro para falta de conexão
import redis
# Conectar diretamente ao Redis, deixará falhar se não estiver disponível
r = redis.Redis(host='localhost', port=6379, db=0, socket_timeout=2.0)
# Tenta executar um ping para testar a conexão - se falhar, o teste quebra
r.ping()

# Importar implementações dos backends
from storage_backends.fs import FileSystemStorage
from storage_backends.redis import RedisStorage

#
# Fixtures para os testes
#

@pytest.fixture(scope="function")
def temp_fs_dir():
    """Cria um diretório temporário para uso com FileSystemStorage."""
    temp_dir = tempfile.mkdtemp(prefix="nadb_test_fs_")
    yield temp_dir
    # Limpar após o teste
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture(scope="function")
def fs_storage(temp_fs_dir):
    """Cria uma instância de FileSystemStorage para testes."""
    storage = FileSystemStorage(temp_fs_dir)
    yield storage

@pytest.fixture(scope="function")
def redis_storage():
    """Cria uma instância de RedisStorage para testes."""
    storage = RedisStorage(host='localhost', port=6379, db=15)  # Use DB 15 for testing
    
    # Limpar todos os dados do teste anterior
    try:
        keys = storage.redis.keys("nadb:*")
        if keys:
            storage.redis.delete(*keys)
    except Exception as e:
        pytest.fail(f"Erro ao limpar o Redis: {e}")
    
    yield storage
    
    # Limpar após o teste
    try:
        keys = storage.redis.keys("nadb:*")
        if keys:
            storage.redis.delete(*keys)
        storage.close_connections()
    except Exception as e:
        pytest.fail(f"Erro ao limpar o Redis após teste: {e}")

#
# Testes FileSystemStorage
#

def test_fs_directory_permissions(temp_fs_dir):
    """Testa verificação de permissões de diretório no FileSystemStorage."""
    # Criar storage com diretório existente
    fs = FileSystemStorage(temp_fs_dir)
    assert os.path.exists(temp_fs_dir)
    
    # Verificar permissões no diretório existente
    result = fs._check_directory_permissions(temp_fs_dir)
    assert result is True, "Permissões de diretório deveriam estar corretas"
    
    # Criar storage com diretório não existente
    nonexistent_dir = os.path.join(temp_fs_dir, "nonexistent_dir")
    fs2 = FileSystemStorage(nonexistent_dir)
    assert os.path.exists(nonexistent_dir), "Diretório deveria ser criado automaticamente"
    
    # Tentar verificar permissões em um arquivo (não diretório)
    test_file = os.path.join(temp_fs_dir, "test_file.txt")
    with open(test_file, 'w') as f:
        f.write("test")
    result = fs._check_directory_permissions(test_file)
    assert result is False, "Verificação deve falhar em arquivos"

def test_fs_ensure_directory_exists(fs_storage, temp_fs_dir):
    """Testa criação de diretórios aninhados."""
    nested_path = os.path.join(temp_fs_dir, "level1", "level2", "level3", "file.txt")
    
    # O diretório não deve existir inicialmente
    nested_dir = os.path.dirname(nested_path)
    assert not os.path.exists(nested_dir)
    
    # Ensure_directory_exists deve criar o diretório
    result = fs_storage.ensure_directory_exists(nested_path)
    assert result is True
    assert os.path.exists(nested_dir)
    assert os.path.isdir(nested_dir)

def test_fs_atomic_write_operations(fs_storage, temp_fs_dir):
    """Testa operações de escrita atômica no FileSystemStorage."""
    test_path = "test_file.txt"
    test_data = b"test data"
    
    # Escrever dados
    result = fs_storage.write_data(test_path, test_data)
    assert result is True
    
    # Verificar se o arquivo foi criado
    full_path = fs_storage.get_full_path(test_path)
    assert os.path.exists(full_path)
    
    # Ler dados e verificar conteúdo
    with open(full_path, 'rb') as f:
        content = f.read()
    assert content == test_data
    
    # Sobreescrever dados existentes
    new_data = b"updated data"
    result = fs_storage.write_data(test_path, new_data)
    assert result is True
    
    # Verificar se os dados foram atualizados
    with open(full_path, 'rb') as f:
        content = f.read()
    assert content == new_data

def test_fs_delete_directory(fs_storage, temp_fs_dir):
    """Testa exclusão recursiva de diretórios."""
    # Criar estrutura de diretórios aninhados
    nested_dirs = ["dir1", "dir1/subdir1", "dir1/subdir2", "dir2"]
    
    for d in nested_dirs:
        os.makedirs(os.path.join(temp_fs_dir, d), exist_ok=True)
    
    # Criar arquivos nos diretórios
    files = {
        "dir1/file1.txt": b"data1",
        "dir1/subdir1/file2.txt": b"data2",
        "dir1/subdir2/file3.txt": b"data3",
        "dir2/file4.txt": b"data4"
    }
    
    for path, data in files.items():
        fs_storage.write_data(path, data)
        assert fs_storage.file_exists(path)
    
    # Excluir um diretório
    result = fs_storage.delete_directory("dir1")
    assert result is True
    
    # Verificar que dir1 e seus arquivos foram excluídos
    assert not os.path.exists(os.path.join(temp_fs_dir, "dir1"))
    for path in ["dir1/file1.txt", "dir1/subdir1/file2.txt", "dir1/subdir2/file3.txt"]:
        assert not fs_storage.file_exists(path)
    
    # Verificar que dir2 ainda existe
    assert os.path.exists(os.path.join(temp_fs_dir, "dir2"))
    assert fs_storage.file_exists("dir2/file4.txt")

def test_fs_compression_functionality(fs_storage):
    """Testa funcionalidades de compressão e descompressão."""
    # Dados pequenos (não devem ser comprimidos)
    small_data = b"small data"
    
    # Dados grandes (devem ser comprimidos)
    large_data = b"A" * 10000  # Dados altamente compressíveis
    
    # Comprimir dados
    small_compressed = fs_storage.compress_data(small_data, True)
    large_compressed = fs_storage.compress_data(large_data, True)
    
    # Dados pequenos não devem ser comprimidos
    assert small_compressed == small_data
    assert not fs_storage._is_compressed(small_compressed)
    
    # Dados grandes devem ser comprimidos
    assert large_compressed != large_data
    assert fs_storage._is_compressed(large_compressed)
    assert len(large_compressed) < len(large_data)
    
    # Descomprimir dados
    small_decompressed = fs_storage.decompress_data(small_compressed)
    large_decompressed = fs_storage.decompress_data(large_compressed)
    
    # Verificar integridade após descompressão
    assert small_decompressed == small_data
    assert large_decompressed == large_data
    
    # Testar com compressão desativada
    large_uncompressed = fs_storage.compress_data(large_data, False)
    assert large_uncompressed == large_data
    assert not fs_storage._is_compressed(large_uncompressed)

#
# Testes RedisStorage
#

def test_redis_connection_management(temp_fs_dir):
    """Testa gerenciamento de conexões Redis."""
    # Inicializar com parâmetros válidos
    redis_store = RedisStorage(temp_fs_dir, host='localhost', port=6379, db=15)
    assert redis_store.connected is True
    
    # Testar reconexão
    redis_store.connected = False  # Simular desconexão
    assert redis_store._ensure_connection() is True
    assert redis_store.connected is True
    
    # Testar com parâmetros inválidos
    with pytest.raises(redis.ConnectionError):
        # Porta inválida deve gerar exceção
        invalid_store = RedisStorage(temp_fs_dir, host='localhost', port=12345, socket_timeout=1)
        # Forçar tentativa de conexão
        invalid_store._execute_with_retry("test", lambda: True)

def test_redis_data_operations(redis_storage):
    """Testa operações básicas de dados no RedisStorage."""
    # Testar escrita
    test_path = f"test:{uuid.uuid4()}"
    test_data = b"Redis test data"
    
    result = redis_storage.write_data(test_path, test_data)
    assert result is True
    
    # Verificar se os dados existem
    assert redis_storage.file_exists(test_path) is True
    
    # Ler dados
    read_data = redis_storage.read_data(test_path)
    assert read_data == test_data
    
    # Verificar tamanho
    size = redis_storage.get_file_size(test_path)
    assert size == len(test_data)
    
    # Excluir dados
    delete_result = redis_storage.delete_file(test_path)
    assert delete_result is True
    
    # Verificar exclusão
    assert redis_storage.file_exists(test_path) is False
    assert redis_storage.read_data(test_path) is None

def test_redis_metadata_operations(redis_storage):
    """Testa operações de metadados no RedisStorage."""
    # Limpar o banco de dados Redis antes de iniciar o teste
    redis_storage.redis.flushdb()
    
    # Criar metadados
    key = f"metadata_test:{uuid.uuid4()}"
    db = "testdb"
    namespace = "testns"
    
    metadata = {
        "key": key,
        "db": db,
        "namespace": namespace,
        "size": 1024,
        "created": datetime.now().isoformat(),
        "tags": ["test", "metadata", "redis"],
        "ttl": 3600
    }
    
    # Definir metadados
    redis_storage.set_metadata(metadata)
    
    # Recuperar metadados
    retrieved = redis_storage.get_metadata(key, db, namespace)
    
    # Verificar se todos os campos foram armazenados corretamente
    assert retrieved["key"] == key
    assert retrieved["db"] == db
    assert retrieved["namespace"] == namespace
    assert retrieved["size"] == 1024
    assert "created" in retrieved
    assert set(retrieved["tags"]) == set(["test", "metadata", "redis"])
    assert retrieved["ttl"] == 3600
    
    # Consultar por tags
    query = {
        "db": db,
        "namespace": namespace,
        "tags": ["test", "metadata"]
    }
    
    results = redis_storage.query_metadata(query)
    
    assert len(results) == 1
    assert results[0]["key"] == key
    
    # Excluir metadados
    redis_storage.delete_metadata(key, db, namespace)
    
    # Verificar exclusão
    retrieved = redis_storage.get_metadata(key, db, namespace)
    assert retrieved is None

def test_redis_ttl_functionality(redis_storage):
    """Testa funcionalidade de TTL (Time To Live) no RedisStorage."""
    # Criar metadados com TTL curto
    key = f"ttl_test:{uuid.uuid4()}"
    db = "testdb"
    namespace = "testns"
    short_ttl = 2  # 2 segundos
    
    # Criar metadados com TTL
    metadata = {
        "key": key,
        "db": db,
        "namespace": namespace,
        "size": 100,
        "created": datetime.now().isoformat(),
        "tags": ["test", "ttl"],
        "ttl": short_ttl,
        "expiry": (datetime.now() + timedelta(seconds=short_ttl)).isoformat()
    }
    
    # Salvar metadados e dados
    redis_storage.set_metadata(metadata)
    redis_storage.write_data(f"{db}:{namespace}:{key}", b"TTL test data")
    
    # Verificar metadados imediatamente
    retrieved = redis_storage.get_metadata(key, db, namespace)
    assert retrieved is not None
    assert retrieved["ttl"] == short_ttl
    
    # Esperar pelo TTL expirar
    time.sleep(short_ttl + 1)
    
    # Limpar itens expirados
    expired = redis_storage.cleanup_expired()
    assert len(expired) >= 1
    assert any(item["key"] == key and item["db"] == db and item["namespace"] == namespace for item in expired)
    
    # Verificar que metadados foram removidos
    retrieved = redis_storage.get_metadata(key, db, namespace)
    assert retrieved is None

def test_redis_query_advanced(redis_storage):
    """Testa recursos avançados de consulta no RedisStorage."""
    # Limpar o banco de dados Redis antes de iniciar o teste
    redis_storage.redis.flushdb()
    
    db = "testdb"
    namespace = "testns"
    
    # Criar vários itens com diferentes tamanhos e tags
    test_items = [
        {"key": "small", "size": 100, "tags": ["size:small", "priority:low"]},
        {"key": "medium", "size": 1000, "tags": ["size:medium", "priority:medium"]},
        {"key": "large", "size": 10000, "tags": ["size:large", "priority:high"]},
        {"key": "critical", "size": 500, "tags": ["size:small", "priority:critical"]}
    ]
    
    # Inserir itens no Redis
    for item in test_items:
        metadata = {
            "key": item["key"],
            "db": db,
            "namespace": namespace,
            "size": item["size"],
            "created": datetime.now().isoformat(),
            "tags": item["tags"]
        }
        redis_storage.set_metadata(metadata)
        redis_storage.write_data(f"{db}:{namespace}:{item['key']}", b"x" * item["size"])
    
    # Consulta por tamanho (todos os itens maiores que 500 bytes)
    size_query = {
        "db": db,
        "namespace": namespace,
        "min_size": 500
    }
    
    size_results = redis_storage.query_metadata(size_query)
    size_keys = [item["key"] for item in size_results]
    assert "small" not in size_keys  # small tem 100 bytes
    assert all(k in size_keys for k in ["medium", "large", "critical"])
    
    # Consulta por tags (todos os itens pequenos e críticos)
    tag_query = {
        "db": db,
        "namespace": namespace,
        "tags": ["size:small", "priority:critical"]
    }
    
    tag_results = redis_storage.query_metadata(tag_query)
    tag_keys = [item["key"] for item in tag_results]
    assert len(tag_keys) == 1
    assert "critical" in tag_keys
    
    # Consulta por data (criados nos últimos 10 segundos)
    time_query = {
        "db": db,
        "namespace": namespace,
        "created_after": (datetime.now() - timedelta(seconds=10)).isoformat()
    }
    
    time_results = redis_storage.query_metadata(time_query)
    assert len(time_results) == len(test_items)  # Todos foram criados agora
    
    # Limpeza
    for item in test_items:
        redis_storage.delete_metadata(item["key"], db, namespace)
        redis_storage.delete_file(f"{db}:{namespace}:{item['key']}") 