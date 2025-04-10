#!/usr/bin/env python3
import json
import time
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, abort
import signal
import sys
import atexit

# Importar NADB
from nadb import KeyValueStore, KeyValueSync

# Variáveis globais para gerenciamento de recursos
kv_sync = None
kv_store = None
app = Flask(__name__)

# Função para limpar recursos
def cleanup_resources():
    global kv_sync, kv_store
    if kv_sync:
        print("Finalizando sincronização NADB...")
        try:
            kv_sync.sync_exit()
            # Dar tempo para as threads finalizarem
            time.sleep(0.5)
        except Exception as e:
            print(f"Erro ao finalizar sincronização: {str(e)}")
    print("Aplicação encerrada.")

# Manipulador de sinais
def signal_handler(sig, frame):
    print("\nInterrompendo aplicação...")
    cleanup_resources()
    sys.exit(0)

# Configurar manipulador de sinal e limpeza ao sair
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
atexit.register(cleanup_resources)

# Configurar NADB com backend Redis
kv_sync = KeyValueSync(flush_interval_seconds=1)  # Flush a cada 1 segundo
kv_sync.start()  # Iniciar thread de sincronização

# Inicializar o KeyValueStore com backend Redis
kv_store = KeyValueStore(
    data_folder_path='./data',  # Local para armazenar dados temporários
    db='todo_app',              # Nome do banco de dados
    buffer_size_mb=1,           # Tamanho do buffer em memória
    namespace='tasks',          # Namespace para as tarefas
    sync=kv_sync,               # Objeto de sincronização
    compression_enabled=True,   # Habilitar compressão
    storage_backend="redis"     # Usar backend Redis
)

# Configurar o backend Redis diretamente após a criação
kv_store.storage.connection_params.update({
    'host': 'localhost',
    'port': 6379,
    'db': 0  # Número do banco Redis
})

# Reconectar com os novos parâmetros
kv_store.storage._connect()

# API Routes
@app.route('/api/boards/<board_id>/tasks', methods=['GET'])
def get_tasks(board_id):
    """Retorna todas as tarefas de um board específico."""
    try:
        # Verificar se há um termo de pesquisa
        search_term = request.args.get('search', '').lower()
        
        # Consultar tarefas específicas deste board
        task_keys = kv_store.query_by_tags([f"task:{board_id}"])
        tasks = []
        
        for key in task_keys:
            try:
                # Obter tarefa com metadados
                result = kv_store.get_with_metadata(key)
                if result:
                    task_data = json.loads(result["value"].decode('utf-8'))
                    # Adicionar key à tarefa para facilitar operações
                    task_data['id'] = key
                    
                    # Filtrar por termo de pesquisa se fornecido
                    if search_term:
                        title = task_data.get('title', '').lower()
                        description = task_data.get('description', '').lower()
                        
                        # Verificar se o termo de pesquisa está no título ou descrição
                        if search_term in title or search_term in description:
                            tasks.append(task_data)
                        else:
                            # Verificar nas subtasks
                            subtasks = task_data.get('subtasks', [])
                            subtask_match = any(search_term in subtask.get('title', '').lower() for subtask in subtasks)
                            if subtask_match:
                                tasks.append(task_data)
                    else:
                    tasks.append(task_data)
            except Exception as e:
                print(f"Erro ao processar tarefa {key}: {str(e)}")
        
        # Ordenar por data de criação (mais recente primeiro)
        tasks.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return jsonify(tasks)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/boards/<board_id>/tasks', methods=['POST'])
def create_task(board_id):
    """Cria uma nova tarefa em um board específico."""
    try:
        data = request.json
        if not data or 'title' not in data:
            return jsonify({"error": "Título da tarefa é obrigatório"}), 400
        
        # Criar nova tarefa com prefixo do board
        task_id = f"task:{board_id}:{uuid.uuid4()}"
        task = {
            "title": data['title'],
            "description": data.get('description', ''),
            "subtasks": data.get('subtasks', []),
            "completed": False,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        
        # Salvar no NADB com tag específica para este board
        kv_store.set(task_id, json.dumps(task).encode('utf-8'), tags=[f"task:{board_id}"])
        
        # Forçar flush para persistir imediatamente
        kv_store.flush()
        
        # Adicionar ID à resposta
        task['id'] = task_id
        return jsonify(task), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/boards/<board_id>/tasks/<task_id>/subtasks', methods=['POST'])
def create_subtask(board_id, task_id):
    """Adiciona uma subtask a uma tarefa existente em um board específico."""
    try:
        data = request.json
        if not data or 'title' not in data:
            return jsonify({"error": "Título da subtask é obrigatório"}), 400
        
        # Verificar se a tarefa pertence ao board correto
        if not task_id.startswith(f"task:{board_id}:"):
            return jsonify({"error": "Tarefa não pertence a este board"}), 403
        
        # Obter tarefa existente
        result = kv_store.get_with_metadata(task_id)
        if not result:
            return jsonify({"error": "Tarefa não encontrada"}), 404
        
            task = json.loads(result["value"].decode('utf-8'))
        
        # Criar nova subtask
        new_subtask = {
            "id": str(uuid.uuid4()),
            "title": data['title'],
            "completed": False
        }
        
        # Adicionar à lista de subtasks (criar se não existir)
        if 'subtasks' not in task:
            task['subtasks'] = []
        
        task['subtasks'].append(new_subtask)
        
        # Atualizar a tarefa
        task['updated_at'] = datetime.now().isoformat()
        kv_store.set(task_id, json.dumps(task).encode('utf-8'), tags=[f"task:{board_id}"])
        kv_store.flush()
        
        # Retornar a tarefa atualizada
            task['id'] = task_id
        return jsonify(task), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/boards/<board_id>/tasks/<task_id>/subtasks/<subtask_id>', methods=['PUT'])
def update_subtask(board_id, task_id, subtask_id):
    """Atualiza uma subtask de uma tarefa em um board específico."""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Dados não fornecidos"}), 400
        
        # Verificar se a tarefa pertence ao board correto
        if not task_id.startswith(f"task:{board_id}:"):
            return jsonify({"error": "Tarefa não pertence a este board"}), 403
        
        # Obter tarefa existente
        result = kv_store.get_with_metadata(task_id)
        if not result:
            return jsonify({"error": "Tarefa não encontrada"}), 404
        
        task = json.loads(result["value"].decode('utf-8'))
        
        # Verificar se a tarefa possui subtasks
        if 'subtasks' not in task:
            return jsonify({"error": "Tarefa não possui subtasks"}), 400
        
        # Encontrar a subtask pelo ID
        subtask_index = next((i for i, st in enumerate(task['subtasks']) if st['id'] == subtask_id), None)
        if subtask_index is None:
            return jsonify({"error": "Subtask não encontrada"}), 404
        
        # Atualizar os campos da subtask
        if 'title' in data:
            task['subtasks'][subtask_index]['title'] = data['title']
        if 'completed' in data:
            task['subtasks'][subtask_index]['completed'] = data['completed']
        
        # Atualizar a tarefa
        task['updated_at'] = datetime.now().isoformat()
        kv_store.set(task_id, json.dumps(task).encode('utf-8'), tags=[f"task:{board_id}"])
        kv_store.flush()
        
        # Retornar a tarefa atualizada
        task['id'] = task_id
        return jsonify(task), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/boards/<board_id>/tasks/<task_id>/subtasks/<subtask_id>', methods=['DELETE'])
def delete_subtask(board_id, task_id, subtask_id):
    """Remove uma subtask de uma tarefa em um board específico."""
    try:
        # Verificar se a tarefa pertence ao board correto
        if not task_id.startswith(f"task:{board_id}:"):
            return jsonify({"error": "Tarefa não pertence a este board"}), 403
        
        # Obter tarefa existente
        result = kv_store.get_with_metadata(task_id)
        if not result:
            return jsonify({"error": "Tarefa não encontrada"}), 404
        
        task = json.loads(result["value"].decode('utf-8'))
        
        # Verificar se a tarefa possui subtasks
        if 'subtasks' not in task:
            return jsonify({"error": "Tarefa não possui subtasks"}), 400
        
        # Filtrar a subtask pelo ID
        original_length = len(task['subtasks'])
        task['subtasks'] = [st for st in task['subtasks'] if st['id'] != subtask_id]
        
        if len(task['subtasks']) == original_length:
            return jsonify({"error": "Subtask não encontrada"}), 404
        
        # Atualizar a tarefa
        task['updated_at'] = datetime.now().isoformat()
        kv_store.set(task_id, json.dumps(task).encode('utf-8'), tags=[f"task:{board_id}"])
        kv_store.flush()
        
        # Retornar a tarefa atualizada
        task['id'] = task_id
        return jsonify(task), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/boards/<board_id>/tasks/<task_id>', methods=['PUT'])
def update_task(board_id, task_id):
    """Atualiza uma tarefa em um board específico."""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Dados não fornecidos"}), 400
        
        # Verificar se a tarefa pertence ao board correto
        if not task_id.startswith(f"task:{board_id}:"):
            return jsonify({"error": "Tarefa não pertence a este board"}), 403
        
        # Verificar se a tarefa existe
        try:
            result = kv_store.get_with_metadata(task_id)
            if not result:
                return jsonify({"error": "Tarefa não encontrada"}), 404
                
            # Obter tarefa atual
            current_task = json.loads(result["value"].decode('utf-8'))
            
            # Atualizar campos
            current_task['title'] = data.get('title', current_task['title'])
            current_task['description'] = data.get('description', current_task['description'])
            current_task['completed'] = data.get('completed', current_task['completed'])
            
            # Atualizar subtasks se fornecidas
            if 'subtasks' in data:
                current_task['subtasks'] = data['subtasks']
                
            current_task['updated_at'] = datetime.now().isoformat()
            
            # Salvar tarefa atualizada
            kv_store.set(task_id, json.dumps(current_task).encode('utf-8'), tags=[f"task:{board_id}"])
            kv_store.flush()
            
            # Adicionar ID à resposta
            current_task['id'] = task_id
            return jsonify(current_task)
        except KeyError:
            return jsonify({"error": "Tarefa não encontrada"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/boards/<board_id>/tasks/<task_id>', methods=['DELETE'])
def delete_task(board_id, task_id):
    """Remove uma tarefa de um board específico."""
    try:
        # Verificar se a tarefa pertence ao board correto
        if not task_id.startswith(f"task:{board_id}:"):
            return jsonify({"error": "Tarefa não pertence a este board"}), 403
        
        # Verificar se a tarefa existe
        try:
            if not kv_store.get(task_id):
                return jsonify({"error": "Tarefa não encontrada"}), 404
                
            # Excluir tarefa
            kv_store.delete(task_id)
            kv_store.flush()
            
            return jsonify({"message": "Tarefa removida com sucesso"})
        except KeyError:
            return jsonify({"error": "Tarefa não encontrada"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/boards/<board_id>/stats', methods=['GET'])
def get_stats(board_id):
    """Retorna estatísticas de um board específico."""
    try:
        # Contar tarefas específicas deste board
        task_keys = kv_store.query_by_tags([f"task:{board_id}"])
        
        return jsonify({
            "total_tasks": len(task_keys),
            "board_id": board_id
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/delete-board/<board_id>')
def delete_board(board_id):
    # Buscar todas as tarefas do board
    task_ids = kv_store.query_by_tags([f"task:{board_id}"])
    
    # Deletar cada tarefa
    with kv_sync.transaction():
        for task_id in task_ids:
            kv_store.delete(task_id)
    
    # Redirecionar para a página inicial
    return redirect('/')

@app.route('/add_subtask/<board_id>/<task_id>/<subtask_title>')
def add_subtask(board_id, task_id, subtask_title):
    # Implemente a lógica para adicionar uma subtarefa a uma tarefa existente
    pass

# Frontend Routes
@app.route('/')
def welcome():
    """Renderiza a página de boas-vindas."""
    welcome_template = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NADB Todo App</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap">
    <style>
        :root {
            --primary: #4361ee;
                --primary-light: #5a73f0;
                --primary-dark: #3b53cc;
            --secondary: #3f37c9;
            --light: #f8f9fa;
                --light-gray: #eaedf0;
            --dark: #212529;
                --border-radius: 8px;
                --shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
                --transition: all 0.3s ease;
            }
            
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
        }
        
        body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: var(--dark);
            background-color: #f5f7fb;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                padding: 1rem;
            }
            
            .welcome-card {
                max-width: 600px;
                background-color: white;
                border-radius: var(--border-radius);
                box-shadow: var(--shadow-lg);
                padding: 3rem;
                text-align: center;
                animation: fadeIn 0.5s ease;
            }
            
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }
            
            h1 {
                color: var(--primary);
                margin-bottom: 1.5rem;
                font-size: 2.5rem;
            }
            
            p {
                color: #666;
                margin-bottom: 2rem;
                font-size: 1.1rem;
            }
            
            .features {
                text-align: left;
                margin: 2rem 0;
                padding: 1.5rem;
                background-color: var(--light);
                border-radius: var(--border-radius);
            }
            
            .features ul {
                padding-left: 1.5rem;
            }
            
            .features li {
                margin-bottom: 0.5rem;
            }
            
            .btn {
                display: inline-block;
                background-color: var(--primary);
                color: white;
                border: none;
                border-radius: var(--border-radius);
                padding: 1rem 2rem;
                font-size: 1.2rem;
                font-weight: 500;
                cursor: pointer;
                transition: var(--transition);
                text-decoration: none;
            }
            
            .btn:hover {
                background-color: var(--primary-dark);
                transform: translateY(-2px);
                box-shadow: var(--shadow);
            }
            
            .footer {
                margin-top: 2rem;
                color: #999;
                font-size: 0.9rem;
            }
        </style>
    </head>
    <body>
        <div class="welcome-card">
            <h1>Bem-vindo ao Todo App</h1>
            <p>Um gerenciador de tarefas simples e poderoso, construído com NADB e Redis.</p>
            
            <div class="features">
                <h3>Recursos:</h3>
                <ul>
                    <li>Crie e gerencie sua própria lista de tarefas</li>
                    <li>Organize com subtarefas</li>
                    <li>Compartilhe seu board com um link único</li>
                    <li>Interface limpa e intuitiva</li>
                </ul>
            </div>
            
            <a href="/create-board" class="btn">Criar Novo Board</a>
            
            <div class="footer">
                <p>Desenvolvido com NADB (Not A Database) usando Redis</p>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(welcome_template)

@app.route('/create-board')
def create_board():
    """Cria um novo board com UUID e redireciona para ele."""
    board_id = str(uuid.uuid4())
    
    # Criar uma tarefa de boas-vindas para o novo board
    task_id = f"task:{board_id}:{uuid.uuid4()}"
    welcome_task = {
        "title": "Bem-vindo ao seu novo Board!",
        "description": "Este é seu espaço pessoal para organizar tarefas. Aqui estão algumas dicas para começar:",
        "subtasks": [
            {"id": str(uuid.uuid4()), "title": "Adicione novas tarefas usando o campo no topo", "completed": False},
            {"id": str(uuid.uuid4()), "title": "Organize com subtarefas", "completed": False},
            {"id": str(uuid.uuid4()), "title": "Marque como concluídas quando terminar", "completed": False},
            {"id": str(uuid.uuid4()), "title": "Compartilhe este board usando a URL", "completed": False}
        ],
        "completed": False,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    
    # Salvar no NADB com tag específica para este board
    kv_store.set(task_id, json.dumps(welcome_task).encode('utf-8'), tags=[f"task:{board_id}"])
    kv_store.flush()
    
    return redirect(f"/app/{board_id}")

@app.route('/app/<board_id>')
def todo_app(board_id):
    # Verificar se o board existe
    tasks = kv_store.query_by_tags([f"task:{board_id}"])
    if not tasks:
        abort(404, description=f"Board '{board_id}' não encontrado")
        
    # Continuar normalmente se o board existir
    tasks_data = []
    
    # Buscar todas as tarefas sem usar shared_lock
    task_ids = kv_store.query_by_tags([f"task:{board_id}"])
    
    for task_id in task_ids:
        task_data = kv_store.get(task_id)
        if task_data:
            tasks_data.append(json.loads(task_data))
    
    # Ordenar tarefas pelo timestamp (mais recentes primeiro)
    tasks_data.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    
    return render_template_string(HTML_TEMPLATE, tasks=tasks_data, board_id=board_id)

# HTML Template para o board de tarefas
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NADB Todo App - Board</title>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary-color: #4a6fa5;
            --secondary-color: #166088;
            --accent-color: #4d9de0;
            --background-color: #f5f7fa;
            --text-color: #333;
            --light-text: #666;
            --danger-color: #e74c3c;
            --success-color: #2ecc71;
            --border-color: #e1e4e8;
            --hover-color: #e9f5ff;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Roboto', sans-serif;
            background-color: var(--background-color);
            color: var(--text-color);
            line-height: 1.6;
            padding-bottom: 80px;
        }
        
        header {
            background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
            color: white;
            padding: 20px 30px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .header-content {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        h1 {
            font-size: 1.8rem;
            font-weight: 500;
        }
        
        .board-id {
            font-size: 0.9rem;
            opacity: 0.8;
            margin-top: 5px;
        }
        
        .board-actions {
            display: flex;
            gap: 10px;
        }
        
        .delete-board-btn {
            background-color: var(--danger-color);
            color: white;
            border: none;
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 0.9rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .delete-board-btn:hover {
            background-color: #c0392b;
        }
        
        .search-container {
            display: flex;
            width: 100%;
            max-width: 400px;
            margin: 0 20px;
        }
        
        #search-input {
            flex: 1;
            border: none;
            border-radius: 4px 0 0 4px;
            padding: 8px 12px;
            font-size: 1rem;
        }
        
        #search-btn {
            background-color: white;
            color: var(--primary-color);
            border: none;
            border-radius: 0 4px 4px 0;
            padding: 8px 15px;
            cursor: pointer;
            font-weight: 500;
        }
        
        .container {
            max-width: 1200px;
            margin: 20px auto;
            padding: 0 20px;
        }
        
        .actions {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .stats {
            font-size: 1rem;
            color: var(--light-text);
        }
        
        .add-task-btn {
            background-color: var(--primary-color);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-size: 1rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s ease;
        }
        
        .add-task-btn:hover {
            background-color: var(--secondary-color);
        }
        
        .task-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }
        
        .task-card {
            background-color: white;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
            overflow: hidden;
            transition: all 0.3s ease;
            display: flex;
            flex-direction: column;
        }
        
        .task-card:hover {
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
            transform: translateY(-2px);
        }
        
        .task-header {
            display: flex;
            align-items: center;
            padding: 15px;
            border-bottom: 1px solid var(--border-color);
            cursor: pointer;
        }
        
        .checkbox {
            appearance: none;
            -webkit-appearance: none;
            height: 20px;
            width: 20px;
            background-color: #fff;
            border: 2px solid var(--border-color);
            border-radius: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 15px;
            flex-shrink: 0;
        }
        
        .checkbox:checked {
            background-color: var(--success-color);
            border-color: var(--success-color);
        }
        
        .checkbox:checked::after {
            content: '\\2714';
            font-size: 14px;
            color: white;
        }
        
        .task-title {
            flex: 1;
            font-size: 1.1rem;
            font-weight: 500;
            margin-right: 10px;
        }
        
        .task-actions {
            display: flex;
            gap: 8px;
        }
        
        .btn {
            background: none;
            border: none;
            cursor: pointer;
            padding: 5px;
            color: var(--light-text);
            border-radius: 4px;
            transition: all 0.2s ease;
        }
        
        .btn:hover {
            background-color: var(--hover-color);
            color: var(--text-color);
        }
        
        .delete-btn:hover {
            background-color: #c82333;
        }
        
        .task-body {
            padding: 15px;
            display: none;
        }
        
        .task-description {
            color: var(--light-text);
            margin-bottom: 15px;
            font-size: 0.95rem;
        }
        
        .subtasks {
            margin-top: 15px;
        }
        
        .subtask {
            display: flex;
            align-items: center;
            margin-bottom: 10px;
            padding: 8px;
            border-radius: 4px;
            background-color: var(--background-color);
        }
        
        .subtask-title {
            flex: 1;
            margin: 0 10px;
            font-size: 0.9rem;
        }
        
        .add-subtask {
            display: flex;
            margin-top: 15px;
            gap: 10px;
        }
        
        .add-subtask input {
            flex: 1;
            padding: 8px 12px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            font-size: 0.9rem;
        }
        
        .add-subtask button {
            background-color: var(--accent-color);
            color: white;
            border: none;
            border-radius: 4px;
            padding: 8px 15px;
            cursor: pointer;
            font-size: 0.9rem;
        }
        
        .edit-form {
            margin-top: 15px;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
            font-size: 0.9rem;
        }
        
        .form-group input,
        .form-group textarea {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            font-size: 0.95rem;
            font-family: inherit;
        }
        
        .form-group textarea {
            min-height: 80px;
            resize: vertical;
        }
        
        .form-actions {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
        }
        
        .save-btn {
            background-color: var(--primary-color);
            color: white;
        }
        
        .cancel-btn {
            background-color: var(--light-text);
            color: white;
        }
        
        .form-btn {
            border: none;
            border-radius: 4px;
            padding: 8px 15px;
            cursor: pointer;
            font-size: 0.9rem;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: var(--light-text);
        }
        
        .empty-state p {
            margin-bottom: 20px;
            font-size: 1.1rem;
        }
        
        .footer {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background-color: white;
            padding: 15px 30px;
            box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.05);
            text-align: center;
            font-size: 0.9rem;
            color: var(--light-text);
        }
        
        .home-link {
            color: var(--primary-color);
            text-decoration: none;
            margin-left: 10px;
        }
        
        .home-link:hover {
            text-decoration: underline;
        }
        
        .expand-icon {
            transition: transform 0.3s ease;
        }
        
        .task-expanded .expand-icon {
            transform: rotate(180deg);
        }
        
        .task-expanded .task-body {
            display: block;
        }
        
        /* Modal CSS */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
            z-index: 1000;
            overflow: auto;
            animation: fadeIn 0.3s;
        }
        
        .modal-content {
            background-color: white;
            margin: 10% auto;
            padding: 25px;
            width: 90%;
            max-width: 500px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            transform: translateY(0);
            animation: slideIn 0.3s;
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .modal-title {
            font-size: 1.5rem;
            font-weight: 500;
            color: var(--primary-color);
        }
        
        .modal-close {
            font-size: 1.5rem;
            color: var(--light-text);
            cursor: pointer;
            background: none;
            border: none;
        }
        
        .modal-form {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        
        .modal-actions {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 20px;
        }
        
        .modal-btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .modal-submit {
            background-color: var(--primary-color);
            color: white;
        }
        
        .modal-submit:hover {
            background-color: var(--secondary-color);
        }
        
        .modal-cancel {
            background-color: #f1f1f1;
            color: var(--light-text);
        }
        
        .modal-cancel:hover {
            background-color: #e1e1e1;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        @keyframes slideIn {
            from { transform: translateY(-50px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        
        @media (max-width: 768px) {
            .header-content {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .search-container {
                margin: 15px 0;
                max-width: 100%;
            }
            
            .task-list {
                grid-template-columns: 1fr;
            }
        }
        
        /* Board actions */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .app-title {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        .home-link {
            color: var(--primary-color);
            text-decoration: none;
            font-size: 0.9rem;
            padding: 5px 10px;
            border: 1px solid var(--primary-color);
            border-radius: 4px;
            transition: all 0.2s ease;
        }
        
        .home-link:hover {
            background-color: var(--primary-color);
            color: white;
        }
        
        .board-actions {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .board-id {
            font-size: 0.9rem;
            color: var(--light-text);
        }
        
        .delete-board-btn {
            background-color: #dc3545;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: all 0.2s ease;
        }
        
        .delete-board-btn:hover {
            background-color: #c82333;
        }
    </style>
</head>
<body>
        <header>
        <div class="header-content">
            <div>
                <h1>NADB Todo App</h1>
                <div class="board-id">Board ID: <span id="board-id">{{ board_id }}</span></div>
            </div>
            <div class="board-actions">
                <button class="delete-board-btn" id="delete-board-btn">Excluir Board</button>
            </div>
            <div class="search-container">
                <input type="text" id="search-input" placeholder="Pesquisar tarefas...">
                <button id="search-btn">Buscar</button>
            </div>
            <a href="/" class="home-link" style="color: white;">Página Inicial</a>
        </div>
        </header>
        
    <div class="container">
        <header class="header">
            <div class="app-title">
                <h1>NADB Todo</h1>
                <a href="/" class="home-link">Voltar para Home</a>
            </div>
            <div class="board-actions">
                <div class="board-id">Board ID: {{board_id}}</div>
                <button class="delete-board-btn">Excluir Board</button>
            </div>
        </header>
        <div class="actions">
            <div class="stats">
                <div class="stat-item" id="total-tasks">
                    Tarefas: <span>0</span>
                </div>
                <div class="stat-item" id="completed-tasks">
                    Concluídas: <span>0</span>
                </div>
                <div class="stat-item" id="pending-tasks">
                    Pendentes: <span>0</span>
                </div>
            </div>
            <button class="add-btn">+ Adicionar Tarefa</button>
        </div>
        
        <div id="task-list" class="task-list">
            <!-- Tasks serão carregadas aqui -->
            <div class="empty-state" id="empty-state" style="display: none;">
                <p>Nenhuma tarefa encontrada</p>
                <button class="add-task-btn" id="add-task-empty-btn">
                    <span>+</span> Adicionar Tarefa
                </button>
            </div>
        </div>
        </div>
        
        <div class="footer">
        NADB Todo App - Powered by NADB
        <a href="/" class="home-link">Voltar para Home</a>
    </div>

    <!-- Modal para adicionar nova tarefa -->
    <div id="addTaskModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 class="modal-title">Nova Tarefa</h2>
                <button class="modal-close">&times;</button>
            </div>
            <form id="newTaskForm" class="modal-form">
                <div>
                    <label for="taskTitle">Título:</label>
                    <input type="text" id="taskTitle" name="taskTitle" required class="form-control">
                </div>
                <div>
                    <label for="taskDescription">Descrição:</label>
                    <textarea id="taskDescription" name="taskDescription" class="form-control"></textarea>
                </div>
                <div class="modal-actions">
                    <button type="button" class="modal-btn modal-cancel">Cancelar</button>
                    <button type="submit" class="modal-btn modal-submit">Adicionar</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const boardId = document.getElementById('board-id').textContent;
        const taskList = document.getElementById('task-list');
            const taskCount = document.getElementById('task-count');
            const emptyState = document.getElementById('empty-state');
            const searchInput = document.getElementById('search-input');
            const searchBtn = document.getElementById('search-btn');
            const addTaskBtn = document.getElementById('add-task-btn');
            const addTaskEmptyBtn = document.getElementById('add-task-empty-btn');
            const deleteBoardBtn = document.getElementById('delete-board-btn');
            
            // Objeto para armazenar IDs de tarefas expandidas
            const expandedTasks = new Set();
            
            // Função para carregar tarefas
            async function loadTasks(searchTerm = '') {
                try {
                    let url = `/api/boards/${boardId}/tasks`;
                    if (searchTerm) {
                        url += `?search=${encodeURIComponent(searchTerm)}`;
                    }
                    
                    const response = await fetch(url);
                    const tasks = await response.json();
                    
                    // Atualizar estatísticas
                    taskCount.textContent = `${tasks.length} tarefa(s)`;
                    
                    // Limpar lista de tarefas
            taskList.innerHTML = '';
            
                    if (tasks.length === 0) {
                        emptyState.style.display = 'block';
                    } else {
                        emptyState.style.display = 'none';
                        
                        // Renderizar tarefas
                        tasks.forEach(task => {
                            const taskCard = createTaskCard(task);
                            taskList.appendChild(taskCard);
                        });
                        
                        // Reabrir tarefas que estavam expandidas antes
                        expandedTasks.forEach(id => {
                            const taskHeader = document.querySelector(`[data-task-id="${id}"] .task-header`);
                            if (taskHeader) {
                                const taskCard = taskHeader.closest('.task-card');
                                taskCard.classList.add('task-expanded');
                            }
                        });
                    }
                } catch (error) {
                    console.error('Erro ao carregar tarefas:', error);
                    taskCount.textContent = 'Erro ao carregar tarefas';
                }
            }
            
            // Criar card de tarefa
            function createTaskCard(task) {
                const isExpanded = expandedTasks.has(task.id);
                const taskCard = document.createElement('div');
                taskCard.className = 'task-card';
                if (isExpanded) {
                    taskCard.classList.add('task-expanded');
                }
                taskCard.setAttribute('data-task-id', task.id);
                
                // Header da tarefa
                const taskHeader = document.createElement('div');
                taskHeader.className = 'task-header';
                
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'checkbox';
                checkbox.checked = task.completed;
                checkbox.addEventListener('change', () => toggleTaskCompletion(task.id, checkbox.checked));
                
                const taskTitle = document.createElement('div');
                taskTitle.className = 'task-title';
                taskTitle.textContent = task.title;
                if (task.completed) {
                    taskTitle.style.textDecoration = 'line-through';
                    taskTitle.style.opacity = '0.7';
                }
                
                const taskActions = document.createElement('div');
                taskActions.className = 'task-actions';
                
                const editBtn = document.createElement('button');
                editBtn.className = 'btn edit-btn';
                editBtn.innerHTML = '✏️';
                editBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showEditForm(task);
                });
                
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'btn delete-btn';
                deleteBtn.innerHTML = '🗑️';
                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    deleteTask(task.id);
                });
                
                const expandBtn = document.createElement('button');
                expandBtn.className = 'btn expand-btn';
                expandBtn.innerHTML = '<span class="expand-icon">▼</span>';
                
                taskActions.appendChild(editBtn);
                taskActions.appendChild(deleteBtn);
                taskActions.appendChild(expandBtn);
                
                taskHeader.appendChild(checkbox);
                taskHeader.appendChild(taskTitle);
                taskHeader.appendChild(taskActions);
                
                // Corpo da tarefa
                const taskBody = document.createElement('div');
                taskBody.className = 'task-body';
                
                if (task.description) {
                    const taskDescription = document.createElement('div');
                    taskDescription.className = 'task-description';
                    taskDescription.textContent = task.description;
                    taskBody.appendChild(taskDescription);
                }
                
                // Subtasks
                if (task.subtasks && task.subtasks.length > 0) {
                    const subtasksContainer = document.createElement('div');
                    subtasksContainer.className = 'subtasks';
                    
                    task.subtasks.forEach(subtask => {
                        const subtaskElement = createSubtask(task.id, subtask);
                        subtasksContainer.appendChild(subtaskElement);
                    });
                    
                    taskBody.appendChild(subtasksContainer);
                }
                
                // Add subtask form
                const addSubtaskForm = document.createElement('div');
                addSubtaskForm.className = 'add-subtask';
                
                const subtaskInput = document.createElement('input');
                subtaskInput.type = 'text';
                subtaskInput.placeholder = 'Adicionar subtarefa...';
                
                const addSubtaskBtn = document.createElement('button');
                addSubtaskBtn.textContent = 'Adicionar';
                addSubtaskBtn.addEventListener('click', () => {
                    const title = subtaskInput.value.trim();
                    if (title) {
                        addSubtask(task.id, title);
                        subtaskInput.value = '';
                    }
                });
                
                addSubtaskForm.appendChild(subtaskInput);
                addSubtaskForm.appendChild(addSubtaskBtn);
                taskBody.appendChild(addSubtaskForm);
                
                // Adicionar header e body ao card
                taskCard.appendChild(taskHeader);
                taskCard.appendChild(taskBody);
                
                // Evento de toggle para expandir/colapsar
                taskHeader.addEventListener('click', () => {
                    taskCard.classList.toggle('task-expanded');
                    if (taskCard.classList.contains('task-expanded')) {
                        expandedTasks.add(task.id);
                    } else {
                        expandedTasks.delete(task.id);
                    }
                });
                
                return taskCard;
            }
            
            // Criar elemento de subtarefa
            function createSubtask(taskId, subtask) {
                const subtaskElement = document.createElement('div');
                subtaskElement.className = 'subtask';
                subtaskElement.setAttribute('data-subtask-id', subtask.id);
                
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'checkbox';
                checkbox.checked = subtask.completed;
                checkbox.addEventListener('change', () => {
                    toggleSubtaskCompletion(taskId, subtask.id, checkbox.checked);
                });
                
                const subtaskTitle = document.createElement('div');
                subtaskTitle.className = 'subtask-title';
                subtaskTitle.textContent = subtask.title;
                if (subtask.completed) {
                    subtaskTitle.style.textDecoration = 'line-through';
                    subtaskTitle.style.opacity = '0.7';
                }
                
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'btn delete-btn';
                deleteBtn.innerHTML = '🗑️';
                deleteBtn.addEventListener('click', () => {
                    deleteSubtask(taskId, subtask.id);
                });
                
                subtaskElement.appendChild(checkbox);
                subtaskElement.appendChild(subtaskTitle);
                subtaskElement.appendChild(deleteBtn);
                
                return subtaskElement;
            }
            
            // Mostrar formulário de edição
            function showEditForm(task) {
                const taskCard = document.querySelector(`[data-task-id="${task.id}"]`);
                const taskBody = taskCard.querySelector('.task-body');
                
                // Esconder conteúdo atual do corpo
                Array.from(taskBody.children).forEach(child => {
                    child.style.display = 'none';
                });
                
                // Criar formulário de edição
                const editForm = document.createElement('div');
                editForm.className = 'edit-form';
                
                const titleGroup = document.createElement('div');
                titleGroup.className = 'form-group';
                
                const titleLabel = document.createElement('label');
                titleLabel.textContent = 'Título';
                
                const titleInput = document.createElement('input');
                titleInput.type = 'text';
                titleInput.value = task.title;
                
                titleGroup.appendChild(titleLabel);
                titleGroup.appendChild(titleInput);
                
                const descGroup = document.createElement('div');
                descGroup.className = 'form-group';
                
                const descLabel = document.createElement('label');
                descLabel.textContent = 'Descrição';
                
                const descInput = document.createElement('textarea');
                descInput.value = task.description || '';
                
                descGroup.appendChild(descLabel);
                descGroup.appendChild(descInput);
                
                const formActions = document.createElement('div');
                formActions.className = 'form-actions';
                
                const cancelBtn = document.createElement('button');
                cancelBtn.className = 'form-btn cancel-btn';
                cancelBtn.textContent = 'Cancelar';
                cancelBtn.addEventListener('click', () => {
                    // Mostrar conteúdo novamente
                    editForm.remove();
                    Array.from(taskBody.children).forEach(child => {
                        child.style.display = '';
                    });
                });
                
                const saveBtn = document.createElement('button');
                saveBtn.className = 'form-btn save-btn';
                saveBtn.textContent = 'Salvar';
                saveBtn.addEventListener('click', async () => {
                    const updatedTask = {
                        title: titleInput.value.trim(),
                        description: descInput.value.trim()
                    };
                    
                    if (updatedTask.title) {
                        await updateTask(task.id, updatedTask);
                    }
                });
                
                formActions.appendChild(cancelBtn);
                formActions.appendChild(saveBtn);
                
                editForm.appendChild(titleGroup);
                editForm.appendChild(descGroup);
                editForm.appendChild(formActions);
                
                taskBody.appendChild(editForm);
                
                // Garantir que o card esteja expandido
                taskCard.classList.add('task-expanded');
                expandedTasks.add(task.id);
                
                // Focar no título
                titleInput.focus();
            }
            
            // Adicionar nova tarefa
            async function addTask() {
                const title = window.prompt('Título da tarefa:');
                if (title && title.trim()) {
                    try {
                        const response = await fetch(`/api/boards/${boardId}/tasks`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({ title })
                        });
                        
                        if (response.ok) {
                            loadTasks();
                        } else {
                            console.error('Erro ao adicionar tarefa');
                        }
            } catch (error) {
                        console.error('Erro ao adicionar tarefa:', error);
                    }
                }
            }
            
            // Excluir tarefa
            async function deleteTask(taskId) {
                if (confirm('Tem certeza que deseja excluir esta tarefa?')) {
                    try {
                        const response = await fetch(`/api/boards/${boardId}/tasks/${taskId}`, {
                            method: 'DELETE'
                        });
                
                if (response.ok) {
                            // Remover da lista de expandidos
                            expandedTasks.delete(taskId);
                            loadTasks(searchInput.value.trim());
                        } else {
                            console.error('Erro ao excluir tarefa');
                }
            } catch (error) {
                        console.error('Erro ao excluir tarefa:', error);
                    }
            }
        }
        
            // Atualizar tarefa
            async function updateTask(taskId, updatedTask) {
            try {
                    const response = await fetch(`/api/boards/${boardId}/tasks/${taskId}`, {
                        method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                        body: JSON.stringify(updatedTask)
                    });
                    
                    if (response.ok) {
                        loadTasks(searchInput.value.trim());
                    } else {
                        console.error('Erro ao atualizar tarefa');
                    }
            } catch (error) {
                    console.error('Erro ao atualizar tarefa:', error);
            }
        }
        
            // Toggle de conclusão de tarefa
            async function toggleTaskCompletion(taskId, completed) {
            try {
                    const response = await fetch(`/api/boards/${boardId}/tasks/${taskId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ completed })
                });
                
                    if (response.ok) {
                        // Atualizar visualmente sem recarregar
                        const taskCard = document.querySelector(`[data-task-id="${taskId}"]`);
                        const taskTitle = taskCard.querySelector('.task-title');
                        
                        if (completed) {
                            taskTitle.style.textDecoration = 'line-through';
                            taskTitle.style.opacity = '0.7';
                        } else {
                            taskTitle.style.textDecoration = 'none';
                            taskTitle.style.opacity = '1';
                        }
                    } else {
                        console.error('Erro ao atualizar status da tarefa');
                        loadTasks(searchInput.value.trim()); // Recarregar em caso de erro
                    }
                } catch (error) {
                    console.error('Erro ao atualizar status da tarefa:', error);
                    loadTasks(searchInput.value.trim()); // Recarregar em caso de erro
                }
            }
            
            // Adicionar subtarefa
            async function addSubtask(taskId, title) {
                try {
                    const response = await fetch(`/api/boards/${boardId}/tasks/${taskId}/subtasks`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ title })
                    });
                    
                    if (response.ok) {
                        const task = await response.json();
                        
                        // Atualizar a lista de subtarefas
                        const taskCard = document.querySelector(`[data-task-id="${taskId}"]`);
                        let subtasksContainer = taskCard.querySelector('.subtasks');
                        
                        if (!subtasksContainer) {
                            subtasksContainer = document.createElement('div');
                            subtasksContainer.className = 'subtasks';
                            const taskBody = taskCard.querySelector('.task-body');
                            taskBody.insertBefore(subtasksContainer, taskBody.querySelector('.add-subtask'));
                        }
                        
                        const latestSubtask = task.subtasks[task.subtasks.length - 1];
                        const subtaskElement = createSubtask(taskId, latestSubtask);
                        subtasksContainer.appendChild(subtaskElement);
                    } else {
                        console.error('Erro ao adicionar subtarefa');
                    }
            } catch (error) {
                    console.error('Erro ao adicionar subtarefa:', error);
                }
            }
            
            // Toggle de conclusão de subtarefa
            async function toggleSubtaskCompletion(taskId, subtaskId, completed) {
                try {
                    const response = await fetch(`/api/boards/${boardId}/tasks/${taskId}/subtasks/${subtaskId}`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ completed })
                    });
                    
                    if (response.ok) {
                        // Atualizar visualmente sem recarregar
                        const subtaskElement = document.querySelector(`[data-task-id="${taskId}"] [data-subtask-id="${subtaskId}"]`);
                        const subtaskTitle = subtaskElement.querySelector('.subtask-title');
                        
                        if (completed) {
                            subtaskTitle.style.textDecoration = 'line-through';
                            subtaskTitle.style.opacity = '0.7';
                        } else {
                            subtaskTitle.style.textDecoration = 'none';
                            subtaskTitle.style.opacity = '1';
                        }
                    } else {
                        console.error('Erro ao atualizar status da subtarefa');
                    }
                } catch (error) {
                    console.error('Erro ao atualizar status da subtarefa:', error);
                }
            }
            
            // Excluir subtarefa
            async function deleteSubtask(taskId, subtaskId) {
                try {
                    const response = await fetch(`/api/boards/${boardId}/tasks/${taskId}/subtasks/${subtaskId}`, {
                    method: 'DELETE'
                });
                
                    if (response.ok) {
                        // Remover elemento sem recarregar
                        const subtaskElement = document.querySelector(`[data-task-id="${taskId}"] [data-subtask-id="${subtaskId}"]`);
                        subtaskElement.remove();
                        
                        // Verificar se ainda há subtarefas
                        const taskCard = document.querySelector(`[data-task-id="${taskId}"]`);
                        const subtasksContainer = taskCard.querySelector('.subtasks');
                        if (subtasksContainer && subtasksContainer.children.length === 0) {
                            subtasksContainer.remove();
                        }
                    } else {
                        console.error('Erro ao excluir subtarefa');
                    }
                } catch (error) {
                    console.error('Erro ao excluir subtarefa:', error);
                }
            }
            
            // Eventos de botões
            addTaskBtn.addEventListener('click', addTask);
            addTaskEmptyBtn.addEventListener('click', addTask);
            deleteBoardBtn.addEventListener('click', () => {
                if (confirm('Tem certeza que deseja excluir este board?')) {
                    deleteBoard(boardId);
                }
            });
            
            // Pesquisa
            searchBtn.addEventListener('click', () => {
                loadTasks(searchInput.value.trim());
            });
            
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    loadTasks(searchInput.value.trim());
                }
            });
            
            // Carregar tarefas ao iniciar
            loadTasks();
            
            // Atualizar estatísticas
            async function updateStats() {
                try {
                    const response = await fetch(`/api/boards/${boardId}/stats`);
                    const stats = await response.json();
                    taskCount.textContent = `${stats.total_tasks} tarefa(s)`;
            } catch (error) {
                    console.error('Erro ao carregar estatísticas:', error);
                }
            }
            
            // Atualizar estatísticas a cada 30 segundos
            updateStats();
            setInterval(updateStats, 30000);

            // Toggle task expanded
            document.querySelectorAll('.task-header').forEach(header => {
                header.addEventListener('click', function(e) {
                    if (!e.target.closest('.task-actions')) {
                        this.closest('.task').classList.toggle('task-expanded');
                    }
                });
            });

            // Modal de adicionar tarefa
            const modal = document.getElementById('addTaskModal');
            const addBtn = document.querySelector('.add-btn');
            const closeBtn = document.querySelector('.modal-close');
            const cancelBtn = document.querySelector('.modal-cancel');
            const taskForm = document.getElementById('newTaskForm');
            
            // Abrir modal
            addBtn.addEventListener('click', function() {
                modal.style.display = 'block';
                document.getElementById('taskTitle').focus();
            });
            
            // Fechar modal
            closeBtn.addEventListener('click', function() {
                modal.style.display = 'none';
            });
            
            cancelBtn.addEventListener('click', function() {
                modal.style.display = 'none';
            });
            
            // Fechar modal se clicar fora
            window.addEventListener('click', function(e) {
                if (e.target === modal) {
                    modal.style.display = 'none';
                }
            });
            
            // Submeter formulário
            taskForm.addEventListener('submit', function(e) {
            e.preventDefault();
                const title = document.getElementById('taskTitle').value;
                const description = document.getElementById('taskDescription').value;
                
                if (title.trim() !== '') {
                    window.location.href = `/add/${board_id}/${encodeURIComponent(title)}/${encodeURIComponent(description || '')}`;
                }
            });
            
            // Excluir board
            const deleteBtn = document.querySelector('.delete-board-btn');
            deleteBtn.addEventListener('click', function() {
                if (confirm('Tem certeza que deseja excluir este board e todas as suas tarefas? Esta ação não pode ser desfeita.')) {
                    window.location.href = `/delete-board/${board_id}`;
                }
            });

            // Toggle subtask completed
            document.querySelectorAll('.subtask-checkbox').forEach(checkbox => {
                checkbox.addEventListener('change', function() {
                    const taskId = this.closest('.task').dataset.taskId;
                    const subtaskId = this.dataset.subtaskId;
                    const completed = this.checked;
                    
                    fetch(`/toggle_subtask/${board_id}/${taskId}/${subtaskId}/${completed}`)
                        .then(response => response.json())
                        .then(data => {
                            if (data.status === 'error') {
                                alert('Erro ao atualizar subtarefa: ' + data.message);
                                this.checked = !completed; // Reverte a mudança
                            } else {
                                updateStats();
                            }
                        })
                        .catch(error => {
                            console.error('Erro:', error);
                            alert('Ocorreu um erro ao atualizar a subtarefa.');
                            this.checked = !completed; // Reverte a mudança
                        });
                });
            });
            
            // Função para atualizar estatísticas
            function updateStats() {
                const tasks = document.querySelectorAll('.task');
                const totalTasks = tasks.length;
                let completedTasks = 0;
                
                tasks.forEach(task => {
                    const checkboxes = task.querySelectorAll('.subtask-checkbox');
                    const completed = Array.from(checkboxes).every(checkbox => checkbox.checked);
                    if (completed && checkboxes.length > 0) {
                        completedTasks++;
                    }
                });
                
                const pendingTasks = totalTasks - completedTasks;
                
                document.querySelector('#total-tasks span').textContent = totalTasks;
                document.querySelector('#completed-tasks span').textContent = completedTasks;
                document.querySelector('#pending-tasks span').textContent = pendingTasks;
            }
            
            // Inicializa estatísticas
            updateStats();
        });
    </script>
</body>
</html>
"""

# Executar aplicação
if __name__ == "__main__":
    # Configurar manipulador de sinal e limpeza ao sair
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup_resources)
    
    print("Inicializando KeyValueStore com Redis...")
    
    try:
        # Configurações do Redis
        redis_host = "localhost"
        redis_port = 6379
        redis_db = 0
        
        # Configurar NADB com backend Redis
        kv_sync = KeyValueSync(flush_interval_seconds=1)  # Flush a cada 1 segundo
        kv_sync.start()  # Iniciar thread de sincronização

        # Inicializar o KeyValueStore com backend Redis
        kv_store = KeyValueStore(
            data_folder_path='./data',  # Local para armazenar dados temporários
            db='todo_app',              # Nome do banco de dados
            buffer_size_mb=1,           # Tamanho do buffer em memória
            namespace='tasks',          # Namespace para as tarefas
            sync=kv_sync,               # Objeto de sincronização
            compression_enabled=True,   # Habilitar compressão
            storage_backend="redis"     # Usar backend Redis
        )
        
        # Configurar o backend Redis diretamente após a criação
        kv_store.storage.connection_params.update({
            'host': redis_host,
            'port': redis_port,
            'db': redis_db  # Número do banco Redis
        })
        
        # Reconectar com os novos parâmetros
        kv_store.storage._connect()
        
        # Executar o app
        app.run(debug=True, use_reloader=False)
    except Exception as e:
        print(f"Erro ao inicializar aplicação: {str(e)}")
    finally:
        pass  # A limpeza será feita pelos manipuladores de sinal e atexit 