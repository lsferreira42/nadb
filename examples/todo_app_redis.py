# Ensure Flask and nadb[redis] are installed:
# pip install Flask nadb[redis]
# Make sure a Redis server is running locally (default port 6379)

import uuid
import json
import atexit
import re # For UUID validation
import functools # Needed for decorator
from flask import Flask, request, render_template_string, jsonify, redirect, url_for, abort # Added abort
from nadb import KeyValueStore, KeyValueSync
import traceback # For better error logging

# --- NADB Setup ---
# Initialize synchronization engine (runs in background)
# Checks every 5 seconds to flush buffer if needed (less relevant for Redis immediate writes)
kv_sync = KeyValueSync(flush_interval_seconds=5)
kv_sync.start()

# Initialize KeyValueStore with Redis backend
# Using db='multi_todo_db' and namespace='lists'
# Buffer size is less critical for Redis as writes often go direct, but still used
kv_store = KeyValueStore(
    data_folder_path='./nadb_data', # FS path needed even for Redis (e.g., future metadata fallback?)
    db='multi_todo_db', # Use a different DB name
    buffer_size_mb=1,
    namespace='lists', # Namespace changed slightly to reflect multiple lists
    sync=kv_sync,
    storage_backend="redis",
    # host="localhost",  # Removed - Not accepted by KeyValueStore constructor
    # port=6379,         # Removed - Not accepted by KeyValueStore constructor
    # db=0,            # Default Redis DB number - Assume backend handles default
    # password=None    # Set if your Redis requires a password - Assume backend handles default
)

# Ensure NADB sync stops gracefully on exit
atexit.register(kv_sync.sync_exit)
print("NADB with Redis backend initialized for Multi-List TODO app.")

# --- Flask App Setup ---
app = Flask(__name__)

# --- Helper Functions (Modified for Multi-List) ---

def generate_list_key_prefix(list_uuid):
    """Generates the NADB key prefix for a given list UUID."""
    # Using a simple prefix convention within the namespace
    return f"list:{list_uuid}:"

def get_task_key(list_uuid, task_id):
    return f"{generate_list_key_prefix(list_uuid)}task:{task_id}"

def get_subtask_key(list_uuid, subtask_id):
    return f"{generate_list_key_prefix(list_uuid)}subtask:{subtask_id}"

def get_all_list_keys(list_uuid):
    """Retrieves all NADB keys (tasks and subtasks) for a specific list UUID."""
    key_prefix = generate_list_key_prefix(list_uuid)
    all_keys = []
    try:
        # Use the storage's query_metadata with a key pattern
        all_metadata = kv_store.storage.query_metadata({
            "db": kv_store.db,
            "namespace": kv_store.namespace,
            "key": f"{key_prefix}*" # Get all keys starting with the list prefix
        }) or []
        all_keys = [meta.get("key") for meta in all_metadata if meta.get("key")]
    except Exception as e:
        print(f"Error querying keys for list {list_uuid}: {e}\n{traceback.format_exc()}")
    return all_keys

# CORRECTED Helper to check list existence efficiently
def check_list_exists(list_uuid):
    """Checks if any key exists for the given list UUID."""
    return bool(get_all_list_keys(list_uuid))

def get_all_tasks_with_subtasks(list_uuid):
    """Retrieves all tasks and resolves their subtasks for a specific list."""
    all_tasks = {}
    all_subtasks = {}
    task_keys = []
    subtask_keys = []
    key_prefix = generate_list_key_prefix(list_uuid)

    try:
        # Attempting prefix scan via Redis storage backend's query_metadata
        # This relies on the backend implementation correctly handling prefixing/patterns
        # The query_metadata in redis.py backend uses SCAN with patterns derived
        # from db:namespace:key - we need to see if querying with a partial key works.
        # Let's query for the prefix directly. If this fails, we might need direct SCAN.
        # NOTE: A more robust way would be direct SCAN access if the backend allows it.
        # Example using direct scan (if storage exposes redis connection):
        # for key_bytes in kv_store.storage.redis.scan_iter(match=f"{kv_store.storage.meta_prefix}{kv_store.db}:{kv_store.namespace}:{key_prefix}*"):
        #    key_str = key_bytes.decode('utf-8').split(':')[-1] # Extract the task/subtask key part

        # Let's try querying with a 'key' pattern first via the abstraction
        all_metadata = kv_store.storage.query_metadata({
            "db": kv_store.db,
            "namespace": kv_store.namespace,
            "key": f"{key_prefix}*" # Using key pattern matching based on prefix
        }) or []

        for meta in all_metadata:
            key_str = meta.get("key") # This should be the full key like 'list:uuid:task:id'
            if key_str:
                if key_str.startswith(f"{key_prefix}task:"):
                    task_keys.append(key_str)
                elif key_str.startswith(f"{key_prefix}subtask:"):
                    subtask_keys.append(key_str)

    except Exception as e:
        print(f"Error querying metadata for list {list_uuid}: {e}\n{traceback.format_exc()}")
        return [] # Return empty on error

    # Fetch all subtasks for this list
    for key in subtask_keys:
        try:
            subtask_data = kv_store.get(key) # Use the full key
            subtask = json.loads(subtask_data.decode('utf-8'))
            # Ensure subtask belongs to the correct list (extra check)
            if subtask.get('list_id') == list_uuid:
                 all_subtasks[subtask['id']] = subtask
        except KeyError:
            print(f"Subtask key {key} found in metadata but not retrievable.")
        except Exception as e:
            print(f"Error fetching/decoding subtask {key}: {e}")

    # Fetch tasks and link subtasks for this list
    for key in task_keys:
        try:
            task_data = kv_store.get(key) # Use the full key
            task = json.loads(task_data.decode('utf-8'))
            # Ensure task belongs to the correct list (extra check)
            if task.get('list_id') == list_uuid:
                task_subtask_ids = task.get('subtasks', [])
                task['subtasks_resolved'] = [all_subtasks.get(sub_id) for sub_id in task_subtask_ids if all_subtasks.get(sub_id)]
                all_tasks[task['id']] = task
        except KeyError:
            print(f"Task key {key} found in metadata but not retrievable.")
        except Exception as e:
            print(f"Error fetching/decoding task {key}: {e}")

    return sorted(all_tasks.values(), key=lambda t: t.get('id', ''))

def get_task(list_uuid, task_id):
    """Retrieves a single task dict for a specific list."""
    key = get_task_key(list_uuid, task_id)
    try:
        task_data = kv_store.get(key)
        task = json.loads(task_data.decode('utf-8'))
        # Verify list_id match
        if task.get('list_id') != list_uuid:
             print(f"Warning: Task {task_id} retrieved but belongs to different list {task.get('list_id')}")
             return None
        return task
    except KeyError:
        return None
    except Exception as e:
        print(f"Error getting task {key}: {e}")
        raise

def get_subtask(list_uuid, subtask_id):
    """Retrieves a single subtask dict for a specific list."""
    # Note: We might not always know the list_uuid when only given subtask_id
    # This design might need adjustment if subtasks are accessed directly without list context
    # For now, assume list_uuid is provided.
    key = get_subtask_key(list_uuid, subtask_id)
    try:
        subtask_data = kv_store.get(key)
        subtask = json.loads(subtask_data.decode('utf-8'))
        # Verify list_id match (Subtasks store parent_task_id, but we need list_id directly)
        # We should add list_id to subtasks when saving.
        if subtask.get('list_id') != list_uuid:
            print(f"Warning: Subtask {subtask_id} retrieved but belongs to different list {subtask.get('list_id')}")
            return None
        return subtask
    except KeyError:
        return None
    except Exception as e:
        print(f"Error getting subtask {key}: {e}")
        raise

def save_task(list_uuid, task_data):
    """Saves task data for a specific list."""
    key = get_task_key(list_uuid, task_data['id'])
    try:
        task_data['list_id'] = list_uuid # Ensure list_id is stored
        task_data.pop('subtasks_resolved', None) # Don't save resolved objects
        value = json.dumps(task_data).encode('utf-8')
        # Add list_id tag for potential querying
        tags = ["task", f"list:{list_uuid}"]
        kv_store.set(key, value, tags=tags)
        print(f"Saved task: {key}")
        return task_data
    except Exception as e:
        print(f"Error saving task {key}: {e}")
        raise

def save_subtask(list_uuid, subtask_data):
    """Saves subtask data for a specific list."""
    key = get_subtask_key(list_uuid, subtask_data['id'])
    parent_task_id = subtask_data['parent_task_id']
    try:
        subtask_data['list_id'] = list_uuid # Ensure list_id is stored
        value = json.dumps(subtask_data).encode('utf-8')
        # Add list_id and parent task tags
        tags = ["subtask", f"list:{list_uuid}", f"parent:{parent_task_id}"]
        kv_store.set(key, value, tags=tags)
        print(f"Saved subtask: {key}")
        return subtask_data
    except Exception as e:
        print(f"Error saving subtask {key}: {e}")
        raise

def delete_task_data(list_uuid, task_id):
    """Deletes task data for a specific list."""
    key = get_task_key(list_uuid, task_id)
    try:
        kv_store.delete(key)
        print(f"Deleted task: {key}")
    except Exception as e:
        print(f"Error deleting task {key}: {e}")
        raise

def delete_subtask_data(list_uuid, subtask_id):
    """Deletes subtask data for a specific list."""
    key = get_subtask_key(list_uuid, subtask_id)
    try:
        kv_store.delete(key)
        print(f"Deleted subtask: {key}")
    except Exception as e:
        print(f"Error deleting subtask {key}: {e}")
        raise

# --- HTML Templates ---

# Template for the landing page
LANDING_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to Multi-List TODO</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 100vh; background-color: #f8f9fa; text-align: center; padding: 20px; }
        .content { background-color: #fff; padding: 40px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); margin-bottom: 30px; max-width: 500px; width: 100%; }
        h1 { color: #007bff; margin-bottom: 15px; }
        h2 { color: #6c757d; margin-top: 30px; margin-bottom: 15px; font-size: 1.2rem; }
        p { color: #6c757d; margin-bottom: 25px; }
        .action-form { margin-bottom: 15px; }
        .action-button {
            background-color: #28a745;
            color: white;
            padding: 12px 25px;
            border: none;
            border-radius: 5px;
            font-size: 1rem;
            cursor: pointer;
            text-decoration: none;
            transition: background-color 0.2s ease;
            display: inline-block; /* Fit content */
        }
        .action-button:hover { background-color: #218838; }
        .join-form input[type="text"] {
            padding: 10px;
            border: 1px solid #ced4da;
            border-radius: 5px;
            margin-right: 5px;
            font-size: 1rem;
            width: calc(100% - 110px); /* Adjust width considering button */
            max-width: 300px;
        }
        .join-form button {
             background-color: #007bff;
             padding: 10px 15px;
             font-size: 1rem;
             /* other styles same as .action-button */
             color: white; border: none; border-radius: 5px; cursor: pointer; transition: background-color 0.2s ease;
        }
         .join-form button:hover { background-color: #0056b3; }
         .error-message { color: #dc3545; margin-top: 10px; font-weight: bold; height: 1.2em; /* Reserve space */}
    </style>
</head>
<body>
    <div class="content">
        <h1>Multi-List TODO App</h1>
        <p>Powered by NADB & Redis</p>

        <h2>Create a New List</h2>
        <form action="{{ url_for('create_list') }}" method="post" class="action-form">
            <button type="submit" class="action-button">Create My TODO List</button>
        </form>

        <h2>Or Join Existing List</h2>
        <form id="join-list-form" class="join-form">
            <input type="text" id="list-id-input" placeholder="Enter List ID (UUID)" required pattern="^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$">
            <button type="submit">Go to List</button>
        </form>
        <div id="join-error" class="error-message"></div>

    </div>

    <script>
        const joinForm = document.getElementById('join-list-form');
        const listIdInput = document.getElementById('list-id-input');
        const joinError = document.getElementById('join-error');

        joinForm.addEventListener('submit', function(event) {
            event.preventDefault();
            const listId = listIdInput.value.trim();
            joinError.textContent = ''; // Clear previous error

            // Basic UUID format validation (HTML5 pattern helps but JS check is good too)
            const uuidRegex = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
            if (!listId) {
                joinError.textContent = 'Please enter a List ID.';
            } else if (!uuidRegex.test(listId)) {
                 joinError.textContent = 'Invalid List ID format.';
            } else {
                // Redirect to the list page
                window.location.href = `/list/${listId}`;
            }
        });
    </script>
</body>
</html>
"""

# Template for the TODO List page
LIST_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NADB TODO List - {{ list_id[:8] }}...</title> {# Shortened title #}
    <style>
        /* CSS remains largely the same */
        :root {
            --primary-color: #007bff; --light-gray: #f8f9fa; --gray: #e9ecef;
            --dark-gray: #6c757d; --success-color: #28a745; --danger-color: #dc3545;
            --border-color: #dee2e6; --background-color: #ffffff; --text-color: #212529;
            --border-radius: 0.3rem; --box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 0;
            padding: 20px; background-color: var(--light-gray); color: var(--text-color); line-height: 1.5;
        }
        .container { max-width: 700px; margin: 20px auto; background-color: var(--background-color); padding: 25px; border-radius: var(--border-radius); box-shadow: var(--box-shadow); }
        h1, h2 { color: var(--primary-color); margin-bottom: 1rem; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem; }
        h1 { font-size: 1.8rem; margin-bottom: 0.25rem; /* Reduce margin */ }
        #list-id-display {
             font-size: 0.9rem; color: var(--dark-gray); margin-bottom: 1rem; margin-top: 0.25rem;
             display: flex; align-items: center; flex-wrap: wrap; /* Allow wrapping */
         }
        #list-id-display code { background-color: var(--gray); padding: 2px 5px; border-radius: 3px; margin-right: 10px; word-break: break-all; /* Break long IDs */ }
        #copy-link-btn {
            background: none; border: none; color: var(--primary-color); cursor: pointer;
             padding: 0 5px; font-size: 0.9em; margin-left: 5px;
         }
         #copy-link-btn:hover { text-decoration: underline; }
        h2 { font-size: 1.4rem; margin-top: 1.5rem; }
        ul { list-style: none; padding: 0; }
        li.task-item, li.subtask-item { margin-bottom: 15px; padding: 15px; border: 1px solid var(--border-color); border-radius: var(--border-radius); background-color: var(--background-color); display: flex; flex-direction: column; transition: background-color 0.2s ease; }
        li.completed { background-color: #f0f0f0; }
        li.completed .item-title { text-decoration: line-through; color: var(--dark-gray); }
        .item-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .item-title { font-size: 1.1rem; font-weight: 500; flex-grow: 1; margin-right: 10px; }
        .item-actions button { padding: 5px 10px; font-size: 0.85rem; cursor: pointer; border: 1px solid transparent; border-radius: var(--border-radius); margin-left: 5px; transition: background-color 0.2s ease, border-color 0.2s ease; }
        .item-actions .toggle-btn { background-color: #e0e0e0; border-color: #d0d0d0; }
        .item-actions .toggle-btn.completed { background-color: var(--success-color); color: white; border-color: var(--success-color); }
        .item-actions .delete-btn { background-color: #f8d7da; color: var(--danger-color); border-color: #f5c6cb; }
        .item-actions button:hover { opacity: 0.8; }
        .subtasks-container { margin-left: 20px; margin-top: 10px; border-left: 3px solid var(--gray); padding-left: 15px; }
        .subtasks-list li { font-size: 0.95em; margin-bottom: 10px; padding: 10px; }
        .add-subtask-form { margin-top: 10px; }
        .add-form { margin-top: 20px; padding: 15px; background-color: var(--light-gray); border: 1px solid var(--border-color); border-radius: var(--border-radius); display: flex; }
        .add-form input[type="text"] { flex-grow: 1; padding: 10px; margin-right: 10px; border: 1px solid var(--border-color); border-radius: var(--border-radius); font-size: 1rem; }
        .add-form button { padding: 10px 20px; cursor: pointer; background-color: var(--primary-color); color: white; border: none; border-radius: var(--border-radius); font-size: 1rem; transition: background-color 0.2s ease; }
        .add-form button:hover { background-color: #0056b3; }
        .loading { text-align: center; padding: 20px; color: var(--dark-gray); }
        .error { color: var(--danger-color); font-weight: bold; margin-top: 10px; }
        .list-actions { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border-color); text-align: right; }
        .delete-list-btn {
             background-color: var(--danger-color);
             color: white;
             padding: 8px 15px;
             border: none; border-radius: var(--border-radius);
             font-size: 0.9rem; cursor: pointer; transition: background-color 0.2s ease;
        }
        .delete-list-btn:hover { background-color: #c82333; }
        footer { margin-top: 1rem; text-align: center; font-size: 0.85rem; color: var(--dark-gray); }
    </style>
</head>
<body data-list-id="{{ list_id }}"> {# Pass list_id to JS via data attribute #}
    <div class="container">
        <h1>TODO List</h1>
        {# Display List ID and Copy Button #}
        <div id="list-id-display">
            List ID: <code>{{ list_id }}</code>
            <button id="copy-link-btn" title="Copy list URL">Copy Link</button>
        </div>

        <h2>Add New Task</h2>
        <form id="add-task-form" class="add-form">
            <input type="text" name="title" placeholder="What needs to be done?" required>
            <button type="submit">Add Task</button>
        </form>
        <div id="error-message" class="error" style="display: none;"></div>

        <h2>Tasks</h2>
        <div id="task-list-container">
            <div id="loading-tasks" class="loading">Loading tasks...</div>
            <ul id="task-list">
                <!-- Tasks will be loaded here by JavaScript -->
            </ul>
        </div>

         {# List Actions - Delete List #}
         <div class="list-actions">
             <button id="delete-list-btn" class="delete-list-btn">Delete This List</button>
         </div>

         <footer>
             NADB Backend: {{ kv_store.storage.__class__.__name__ }} | DB: {{ kv_store.db }} | Namespace: {{ kv_store.namespace }}
         </footer>
    </div>

    <script>
        // Get list_id from body data attribute
        const LIST_ID = document.body.dataset.listId;

        const taskList = document.getElementById('task-list');
        const addTaskForm = document.getElementById('add-task-form');
        const loadingIndicator = document.getElementById('loading-tasks');
        const errorMessageDiv = document.getElementById('error-message');
        const copyLinkBtn = document.getElementById('copy-link-btn');
        const deleteListBtn = document.getElementById('delete-list-btn');

        // --- API Helper (remains the same) ---
        async function apiRequest(endpoint, method = 'GET', data = null) {
            const url = `/api/list/${LIST_ID}${endpoint}`;
            const options = { method: method, headers: { 'Content-Type': 'application/json', }, };
            if (data) { options.body = JSON.stringify(data); }
            try {
                const response = await fetch(url, options);
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ message: `HTTP error! status: ${response.status}` }));
                    throw new Error(errorData.message || `Request failed with status ${response.status}`);
                }
                 // Handle 204 No Content for DELETE
                if (method === 'DELETE' && response.status === 204) { return { success: true }; }
                // Handle potential 204 No Content for GET (if list becomes empty after loading)
                 if (method === 'GET' && response.status === 204) { return []; }
                return await response.json();
            } catch (error) {
                console.error('API Request Error:', url, method, error);
                showError(error.message);
                throw error;
            }
        }

        // --- Error Handling (remains the same) ---
        function showError(message) {
            errorMessageDiv.textContent = `Error: ${message}`;
            errorMessageDiv.style.display = 'block';
            setTimeout(() => { errorMessageDiv.style.display = 'none'; }, 5000);
        }

        // --- Rendering Functions (remain the same) ---
        function renderTask(task) {
            const subtasksHtml = (task.subtasks_resolved || []).map(renderSubtask).join('');
            const li = document.createElement('li');
            li.id = `task-${task.id}`;
            li.className = `task-item ${task.completed ? 'completed' : ''}`; li.dataset.taskId = task.id;
            li.innerHTML = `
                <div class="item-header">
                    <span class="item-title">${escapeHTML(task.title)}</span>
                    <div class="item-actions">
                        <button class="toggle-btn ${task.completed ? 'completed' : ''}" data-action="toggle">${task.completed ? 'Undo' : 'Complete'}</button>
                        <button class="delete-btn" data-action="delete">Delete</button>
                    </div>
                </div>
                <div class="subtasks-container">
                    <ul class="subtasks-list" id="subtasks-for-${task.id}">${subtasksHtml}</ul>
                    <form class="add-subtask-form" data-task-id="${task.id}">
                        <input type="text" name="title" placeholder="Add subtask..." required>
                        <button type="submit">Add</button>
                    </form>
                </div>
            `;
            li.querySelector('.toggle-btn').addEventListener('click', handleToggleTask);
            li.querySelector('.delete-btn').addEventListener('click', handleDeleteTask);
            li.querySelector('.add-subtask-form').addEventListener('submit', handleAddSubtask);
            li.querySelectorAll('.subtask-item .toggle-btn').forEach(btn => btn.addEventListener('click', handleToggleSubtask));
            li.querySelectorAll('.subtask-item .delete-btn').forEach(btn => btn.addEventListener('click', handleDeleteSubtask));
            return li;
        }
        function renderSubtask(subtask) {
             if (!subtask || !subtask.id) return '';
             return `
                <li id="subtask-${subtask.id}" class="subtask-item ${subtask.completed ? 'completed' : ''}" data-subtask-id="${subtask.id}">
                    <div class="item-header">
                        <span class="item-title">${escapeHTML(subtask.title)}</span>
                        <div class="item-actions">
                            <button class="toggle-btn ${subtask.completed ? 'completed' : ''}" data-action="toggle">${subtask.completed ? 'Undo' : 'Complete'}</button>
                            <button class="delete-btn" data-action="delete">Delete</button>
                        </div>
                    </div>
                </li>
            `;
        }
        function escapeHTML(str) {
            const div = document.createElement('div');
            div.appendChild(document.createTextNode(str || ''));
            return div.innerHTML;
        }

        // --- Event Handlers (updated API endpoints, added copy/delete) ---
        async function handleAddTask(event) {
            event.preventDefault();
            const titleInput = addTaskForm.querySelector('input[name="title"]');
            const title = titleInput.value.trim(); if (!title) return;
            try {
                const newTask = await apiRequest('/tasks', 'POST', { title });
                const taskElement = renderTask(newTask);
                // If the list was empty, remove the 'no tasks' message first
                const noTasksLi = taskList.querySelector('li');
                if (noTasksLi && !noTasksLi.dataset.taskId) { noTasksLi.remove(); }
                taskList.appendChild(taskElement);
                titleInput.value = '';
            } catch (error) { /* Handled */ }
        }
        async function handleAddSubtask(event) {
            event.preventDefault();
            const form = event.target; const taskId = form.dataset.taskId;
            const titleInput = form.querySelector('input[name="title"]');
            const title = titleInput.value.trim(); if (!title || !taskId) return;
             try {
                const newSubtask = await apiRequest(`/tasks/${taskId}/subtasks`, 'POST', { title });
                const subtaskHTML = renderSubtask(newSubtask);
                const subtaskListElement = document.getElementById(`subtasks-for-${taskId}`);
                const tempDiv = document.createElement('div'); tempDiv.innerHTML = subtaskHTML.trim();
                const subtaskElement = tempDiv.firstChild;
                if (subtaskListElement && subtaskElement) {
                    subtaskElement.querySelector('.toggle-btn').addEventListener('click', handleToggleSubtask);
                    subtaskElement.querySelector('.delete-btn').addEventListener('click', handleDeleteSubtask);
                    subtaskListElement.appendChild(subtaskElement);
                }
                titleInput.value = '';
            } catch (error) { /* Handled */ }
        }
        async function handleToggleTask(event) {
            const button = event.target; const taskItem = button.closest('.task-item');
            const taskId = taskItem.dataset.taskId; if (!taskId) return;
            try {
                const updatedTask = await apiRequest(`/tasks/${taskId}`, 'PATCH');
                taskItem.classList.toggle('completed', updatedTask.completed);
                button.classList.toggle('completed', updatedTask.completed);
                button.textContent = updatedTask.completed ? 'Undo' : 'Complete';
                taskItem.querySelector('.item-title').classList.toggle('completed', updatedTask.completed);
            } catch (error) { /* Handled */ }
        }
        async function handleToggleSubtask(event) {
             const button = event.target; const subtaskItem = button.closest('.subtask-item');
             const subtaskId = subtaskItem.dataset.subtaskId; if (!subtaskId) return;
             try {
                 const updatedSubtask = await apiRequest(`/subtasks/${subtaskId}`, 'PATCH');
                 subtaskItem.classList.toggle('completed', updatedSubtask.completed);
                 button.classList.toggle('completed', updatedSubtask.completed);
                 button.textContent = updatedSubtask.completed ? 'Undo' : 'Complete';
                 subtaskItem.querySelector('.item-title').classList.toggle('completed', updatedSubtask.completed);
             } catch (error) { /* Handled */ }
        }
        async function handleDeleteTask(event) {
            const button = event.target; const taskItem = button.closest('.task-item');
            const taskId = taskItem.dataset.taskId;
            if (!taskId || !confirm('Are you sure you want to delete this task and ALL its subtasks?')) return;
            try { await apiRequest(`/tasks/${taskId}`, 'DELETE'); taskItem.remove(); }
            catch (error) { /* Handled */ }
        }
        async function handleDeleteSubtask(event) {
            const button = event.target; const subtaskItem = button.closest('.subtask-item');
            const subtaskId = subtaskItem.dataset.subtaskId;
            if (!subtaskId || !confirm('Are you sure you want to delete this subtask?')) return;
             try { await apiRequest(`/subtasks/${subtaskId}`, 'DELETE'); subtaskItem.remove(); }
             catch (error) { /* Handled */ }
        }

        // Handler for Copy Link Button
        function handleCopyLink(event) {
            const urlToCopy = window.location.href;
            navigator.clipboard.writeText(urlToCopy).then(() => {
                // Visual feedback
                const originalText = copyLinkBtn.textContent;
                copyLinkBtn.textContent = 'Copied!';
                copyLinkBtn.disabled = true;
                setTimeout(() => {
                    copyLinkBtn.textContent = originalText;
                    copyLinkBtn.disabled = false;
                }, 1500); // Reset after 1.5 seconds
            }).catch(err => {
                console.error('Failed to copy URL: ', err);
                showError('Could not copy link to clipboard.');
            });
        }

        // Handler for Delete List Button
        async function handleDeleteList(event) {
            if (!LIST_ID || !confirm('Are you absolutely sure you want to delete this entire list and all its tasks? This cannot be undone.')) return;

            try {
                // Make DELETE request to the list endpoint itself
                await apiRequest('', 'DELETE'); // Endpoint is just /api/list/LIST_ID
                // Redirect to landing page on success
                alert('List deleted successfully.'); // Give feedback before redirect
                window.location.href = '/'; // Redirect to landing
            } catch (error) {
                // Error is shown by apiRequest
                console.error('Failed to delete list:', error);
            }
        }

        // --- Initial Load (remains the same) ---
        async function loadTasks() {
            if (!LIST_ID) { showError("List ID is missing. Cannot load tasks."); loadingIndicator.style.display = 'none'; return; }
            loadingIndicator.style.display = 'block'; taskList.innerHTML = ''; errorMessageDiv.style.display = 'none';
            try {
                const tasks = await apiRequest('/tasks');
                 if (tasks && tasks.length > 0) { tasks.forEach(task => taskList.appendChild(renderTask(task))); }
                 else { taskList.innerHTML = '<li>No tasks yet! Add one above.</li>'; }
            } catch (error) { taskList.innerHTML = '<li>Could not load tasks.</li>'; /* Handled */ }
            finally { loadingIndicator.style.display = 'none'; }
        }

        // --- Event Listeners ---
        addTaskForm.addEventListener('submit', handleAddTask);
        copyLinkBtn.addEventListener('click', handleCopyLink);
        deleteListBtn.addEventListener('click', handleDeleteList);

        // Load tasks when the page loads
        document.addEventListener('DOMContentLoaded', loadTasks);

    </script>
</body>
</html>
"""

# NEW Template for 404 List Not Found page
NOT_FOUND_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>404 - List Not Found</title>
    <style>
        :root {
            --primary-color: #007bff; --light-gray: #f8f9fa; --gray: #e9ecef;
            --dark-gray: #6c757d; --danger-color: #dc3545;
            --border-radius: 0.3rem; --box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
        }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; background-color: var(--light-gray); text-align: center; padding: 20px; }
        .content { background-color: #fff; padding: 40px; border-radius: var(--border-radius); box-shadow: var(--box-shadow); max-width: 500px; width: 100%; }
        .status-code { font-size: 5rem; font-weight: bold; color: var(--primary-color); margin-bottom: 0; }
        .message { font-size: 1.5rem; color: var(--dark-gray); margin-top: 0; margin-bottom: 1.5rem; }
        .list-id { font-size: 0.9rem; color: var(--dark-gray); margin-bottom: 2rem; word-break: break-all; }
        .list-id code { background-color: var(--gray); padding: 2px 5px; border-radius: 3px; }
        .home-link {
            background-color: var(--primary-color);
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: var(--border-radius);
            font-size: 1rem;
            cursor: pointer;
            text-decoration: none;
            transition: background-color 0.2s ease;
            display: inline-block;
        }
        .home-link:hover { background-color: #0056b3; }
    </style>
</head>
<body>
    <div class="content">
        <div class="status-code">404</div>
        <div class="message">List Not Found</div>
        <div class="list-id">The requested List ID was not found:<br><code>{{ requested_id }}</code></div>
        <a href="{{ url_for('landing_page') }}" class="home-link">Return Home</a>
    </div>
</body>
</html>
"""

# --- Flask Routes ---

@app.route('/')
def landing_page():
    """Serves the landing page."""
    return render_template_string(LANDING_TEMPLATE)

@app.route('/create_list', methods=['POST'])
def create_list():
    """Generates a new list UUID, creates a placeholder, and redirects."""
    new_list_id = str(uuid.uuid4())
    placeholder_key = f"{generate_list_key_prefix(new_list_id)}_exists"
    try:
        # Create a placeholder entry to mark the list as existing
        kv_store.set(placeholder_key, b'1', tags=[f"list:{new_list_id}", "placeholder"])
        print(f"Created placeholder for new list: {new_list_id}")
        # Redirect to the new list's page only if placeholder creation succeeded
        return redirect(url_for('show_list', list_uuid=new_list_id))
    except Exception as e:
        print(f"Error creating placeholder key for new list {new_list_id}: {e}\n{traceback.format_exc()}")
        # Optional: Show an error page or redirect back to landing with an error message
        # For simplicity, just return an error response here
        # Or potentially, render the landing page again with an error context
        return "Failed to create new list. Please try again.", 500

@app.route('/list/<list_uuid>')
def show_list(list_uuid):
    """Serves the main HTML page or a custom 404 page."""
    # Validate UUID format
    if not re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', list_uuid):
        # For invalid format, a simple 400 is okay, or a custom bad request page
        abort(400, description="Invalid List ID format")

    # Check if the list exists (has any keys)
    if not check_list_exists(list_uuid):
        # Render the custom 404 template with a 404 status code
        return render_template_string(NOT_FOUND_TEMPLATE, requested_id=list_uuid), 404

    # List exists, render the normal list page
    return render_template_string(LIST_TEMPLATE, list_id=list_uuid, kv_store=kv_store)

# --- API Routes (Now Prefixed with /api/list/<list_uuid>) ---

# CORRECTED Decorator definition
def check_list(func):
    @functools.wraps(func)
    def wrapper(list_uuid, *args, **kwargs):
        # Validate UUID format first
        if not re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', list_uuid):
             return jsonify({"message": "Invalid List ID format"}), 400
        # Check if list exists in storage only for ops that require it (GET, PATCH, DELETE)
        # POST operations (create task) can proceed even if list has no keys yet.
        # The DELETE list operation checks existence internally.
        if request.method != 'POST' and func.__name__ != 'api_delete_list': # Don't check for POSTs or the main list DELETE
            if not check_list_exists(list_uuid):
                return jsonify({"message": "List not found"}), 404
        return func(list_uuid, *args, **kwargs)
    return wrapper

@app.route('/api/list/<list_uuid>/tasks', methods=['GET'])
@check_list
def api_get_tasks(list_uuid):
    """Returns all tasks and their subtasks for a specific list as JSON."""
    try:
        tasks = get_all_tasks_with_subtasks(list_uuid)
        return jsonify(tasks or [])
    except Exception as e:
        print(f"Error in GET /api/list/{list_uuid}/tasks: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Failed to retrieve tasks"}), 500

@app.route('/api/list/<list_uuid>/tasks', methods=['POST'])
# @check_list # No check needed - POST creates the first entry if list doesn't exist
def api_add_task(list_uuid):
    """Creates a new task for a specific list."""
     # Validate UUID format manually here since decorator is skipped
    if not re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', list_uuid):
        return jsonify({"message": "Invalid List ID format"}), 400

    data = request.get_json()
    if not data or 'title' not in data or not data['title'].strip():
        return jsonify({"message": "Task title is required"}), 400
    try:
        new_task = { "id": str(uuid.uuid4()), "title": data['title'].strip(), "completed": False, "subtasks": [] }
        saved_task = save_task(list_uuid, new_task)
        return jsonify(saved_task), 201
    except Exception as e:
        print(f"Error in POST /api/list/{list_uuid}/tasks: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Failed to create task"}), 500

@app.route('/api/list/<list_uuid>/tasks/<task_id>/subtasks', methods=['POST'])
@check_list # Check list exists before adding subtask to a task within it
def api_add_subtask(list_uuid, task_id):
    """Adds a subtask to a specific task within a list."""
    task = get_task(list_uuid, task_id)
    if not task:
        return jsonify({"message": "Parent task not found in this list"}), 404
    data = request.get_json()
    if not data or 'title' not in data or not data['title'].strip():
        return jsonify({"message": "Subtask title is required"}), 400
    try:
        new_subtask = { "id": str(uuid.uuid4()), "title": data['title'].strip(), "completed": False, "parent_task_id": task_id }
        saved_subtask = save_subtask(list_uuid, new_subtask)
        if 'subtasks' not in task: task['subtasks'] = []
        if new_subtask['id'] not in task['subtasks']:
             task['subtasks'].append(new_subtask['id'])
             save_task(list_uuid, task)
        return jsonify(saved_subtask), 201
    except Exception as e:
        print(f"Error in POST /api/list/{list_uuid}/tasks/.../subtasks: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Failed to create subtask"}), 500

@app.route('/api/list/<list_uuid>/tasks/<task_id>', methods=['PATCH'])
@check_list
def api_toggle_task(list_uuid, task_id):
    """Toggles the completion status of a task in a specific list."""
    task = get_task(list_uuid, task_id)
    if not task:
        return jsonify({"message": "Task not found in this list"}), 404
    try:
        task['completed'] = not task.get('completed', False)
        updated_task = save_task(list_uuid, task)
        return jsonify(updated_task)
    except Exception as e:
        print(f"Error in PATCH /api/list/{list_uuid}/tasks/{task_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Failed to update task"}), 500

@app.route('/api/list/<list_uuid>/subtasks/<subtask_id>', methods=['PATCH'])
@check_list
def api_toggle_subtask(list_uuid, subtask_id):
    """Toggles the completion status of a subtask in a specific list."""
    subtask = get_subtask(list_uuid, subtask_id)
    if not subtask:
         # If list_uuid wasn't correct, get_subtask returns None
        return jsonify({"message": "Subtask not found in this list"}), 404
    try:
        subtask['completed'] = not subtask.get('completed', False)
        updated_subtask = save_subtask(list_uuid, subtask)
        return jsonify(updated_subtask)
    except Exception as e:
        print(f"Error in PATCH /api/list/{list_uuid}/subtasks/{subtask_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Failed to update subtask"}), 500

@app.route('/api/list/<list_uuid>/tasks/<task_id>', methods=['DELETE'])
@check_list
def api_delete_task(list_uuid, task_id):
    """Deletes a task and its associated subtasks from a specific list."""
    task = get_task(list_uuid, task_id)
    if not task:
        return jsonify({"message": "Task not found in this list"}), 404
    try:
        # Delete associated subtasks first, passing list_uuid
        for subtask_id in task.get('subtasks', []):
            try:
                # We need list_uuid to delete subtasks correctly now
                delete_subtask_data(list_uuid, subtask_id)
            except Exception as sub_e:
                 print(f"Error deleting subtask {subtask_id} during task deletion: {sub_e}")
        # Delete the task itself
        delete_task_data(list_uuid, task_id)
        return '', 204
    except Exception as e:
        print(f"Error in DELETE /api/list/{list_uuid}/tasks/{task_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Failed to delete task"}), 500

@app.route('/api/list/<list_uuid>/subtasks/<subtask_id>', methods=['DELETE'])
@check_list
def api_delete_subtask(list_uuid, subtask_id):
    """Deletes a single subtask from a list and removes its reference from the parent."""
    # Use list_uuid to find the subtask
    subtask = get_subtask(list_uuid, subtask_id)
    if not subtask:
        return jsonify({"message": "Subtask not found in this list"}), 404
    try:
        parent_task_id = subtask.get('parent_task_id')
        # Delete the subtask data using list_uuid
        delete_subtask_data(list_uuid, subtask_id)
        # Attempt to remove reference from parent task using list_uuid
        if parent_task_id:
            parent_task = get_task(list_uuid, parent_task_id)
            if parent_task and 'subtasks' in parent_task:
                 if subtask_id in parent_task['subtasks']:
                    parent_task['subtasks'].remove(subtask_id)
                    save_task(list_uuid, parent_task) # Re-save parent
        return '', 204
    except Exception as e:
        print(f"Error in DELETE /api/list/{list_uuid}/subtasks/{subtask_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Failed to delete subtask or update parent reference"}), 500

# Modified API endpoint for deleting an entire list (uses decorator)
@app.route('/api/list/<list_uuid>', methods=['DELETE'])
# @check_list # Removed decorator, check is done manually inside
def api_delete_list(list_uuid):
    """Deletes an entire list and all its associated data."""
    # Manual UUID validation first
    if not re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', list_uuid):
        return jsonify({"message": "Invalid List ID format"}), 400
    
    # Check existence before attempting delete
    keys_to_delete = get_all_list_keys(list_uuid)
    if not keys_to_delete:
        # If no keys found, the list effectively doesn't exist or is empty.
        # Return 404 to indicate it wasn't found for deletion.
        return jsonify({"message": "List not found"}), 404
        
    try:
        deleted_count = 0
        for key in keys_to_delete:
            try:
                kv_store.delete(key)
                deleted_count += 1
            except Exception as del_e:
                print(f"Error deleting key {key} during list deletion: {del_e}")
                # Continue trying to delete other keys
        print(f"Deleted {deleted_count} keys for list {list_uuid}.")
        return '', 204 # No Content success response
    except Exception as e:
        print(f"Error in DELETE /api/list/{list_uuid}: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Failed to delete list"}), 500

# --- Run App ---
if __name__ == '__main__':
    print("Starting Flask server (Multi-List AJAX version) on http://127.0.0.1:5001")
    app.run(debug=True, port=5001, threaded=True) 