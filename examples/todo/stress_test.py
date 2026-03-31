# examples/stress_test.py
import requests
import uuid
import time
import concurrent.futures
import functools
import random
import argparse # Import argparse

# --- Configuration ---
BASE_URL = "http://127.0.0.1:5001" # Make sure todo_app_redis.py is running
NUM_LISTS = 1000  # Reduced for quicker testing - Increase to 10000 for full stress
NUM_TASKS_PER_LIST = 20 # Reduced - Increase to 100
NUM_SUBTASKS_PER_TASK = 3 # Reduced - Increase to 5
MAX_WORKERS = 10        # Adjust based on your machine's capability and server capacity

print(f"Stress Test Configuration:")
print(f" - Target API: {BASE_URL}")
print(f" - Lists to create: {NUM_LISTS}")
print(f" - Tasks per list: {NUM_TASKS_PER_LIST}")
print(f" - Subtasks per task: {NUM_SUBTASKS_PER_TASK}")
print(f" - Max concurrent workers: {MAX_WORKERS}")
print("-" * 30)

# --- Helper Functions ---

def handle_request(func):
    """Decorator to handle common request errors and responses."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            response = func(*args, **kwargs)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            # Check for JSON response if expected
            if response.content:
                 # Handle potential empty success response (e.g., from DELETE)
                 if response.status_code == 204:
                      return {"success": True} # Simulate a success dict for consistency
                 try:
                    return response.json()
                 except requests.exceptions.JSONDecodeError:
                    print(f"Warning: Non-JSON response received (Status {response.status_code}): {response.text[:100]}")
                    # Return a success indicator if status code suggests success (e.g., 200, 201)
                    if 200 <= response.status_code < 300:
                         return {"success": True, "status_code": response.status_code}
                    else:
                         return {"error": "Non-JSON response", "status_code": response.status_code}
            elif 200 <= response.status_code < 300:
                 # Empty response but success status code
                 return {"success": True, "status_code": response.status_code}
            else:
                 # Empty response and error status code
                 print(f"Error: Empty response with status {response.status_code}")
                 return {"error": f"Empty response with status {response.status_code}", "status_code": response.status_code}

        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err} - {http_err.response.text[:200]}")
        except requests.exceptions.ConnectionError as conn_err:
            print(f"Connection error occurred: {conn_err}")
        except requests.exceptions.Timeout as timeout_err:
            print(f"Timeout error occurred: {timeout_err}")
        except requests.exceptions.RequestException as req_err:
            print(f"An unexpected request error occurred: {req_err}")
        except Exception as e:
            print(f"An unexpected error occurred during request: {e}")
        return None # Indicate failure
    return wrapper

# --- API Call Functions ---
@handle_request
def call_create_task_api(session, base_url, list_id, task_title):
    url = f"{base_url}/api/list/{list_id}/tasks"
    payload = {"title": task_title}
    response = session.post(url, json=payload, timeout=20)
    return response

@handle_request
def call_create_subtask_api(session, base_url, list_id, task_id, subtask_title):
    url = f"{base_url}/api/list/{list_id}/tasks/{task_id}/subtasks"
    payload = {"title": subtask_title}
    response = session.post(url, json=payload, timeout=20)
    return response

# --- Worker Functions ---
def create_tasks_for_list(session, base_url, list_id, num_tasks, task_workers):
    """Creates multiple tasks for a given list ID concurrently."""
    task_ids = []
    futures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=task_workers, thread_name_prefix=f"TaskWorker_L{list_id[:4]}") as executor:
        for i in range(num_tasks):
            task_title = f"List {list_id[:6]} - Task {i+1}"
            futures.append(executor.submit(call_create_task_api, session, base_url, list_id, task_title))
        for future in concurrent.futures.as_completed(futures):
            try:
                task_data = future.result()
                if task_data and task_data.get("id"):
                    task_ids.append(task_data["id"])
            except Exception as exc:
                print(f"  Task creation for list {list_id} generated an exception: {exc}")
    return task_ids

def create_subtasks_for_task(session, base_url, list_id, task_id, num_subtasks, task_workers):
    """Creates multiple subtasks for a given task ID concurrently."""
    subtasks_created_count = 0
    futures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=task_workers, thread_name_prefix=f"SubtaskWorker_T{task_id[:4]}") as executor:
        for j in range(num_subtasks):
            subtask_title = f"List {list_id[:6]} - Task {task_id[:6]} - Subtask {j+1}"
            futures.append(executor.submit(call_create_subtask_api, session, base_url, list_id, task_id, subtask_title))
        for future in concurrent.futures.as_completed(futures):
            try:
                subtask_data = future.result()
                if subtask_data and subtask_data.get("success"):
                    subtasks_created_count += 1
            except Exception as exc:
                 print(f"  Subtask creation for task {task_id} generated an exception: {exc}")
    return subtasks_created_count

def create_list_content(list_num, base_url, num_tasks, num_subtasks, task_workers, total_lists):
    """
    Creates a list UUID and then uses a dedicated ThreadPoolExecutor
    to create its tasks and subtasks concurrently.
    """
    list_id = str(uuid.uuid4())
    list_start_time = time.time()
    # Use total_lists argument here
    print(f"[List {list_num+1}/{total_lists}] START Creating list {list_id}...")

    tasks_created_ids = []
    subtasks_created_count = 0

    with requests.Session() as session:
        try:
            # Pass task_workers correctly
            tasks_created_ids = create_tasks_for_list(session, base_url, list_id, num_tasks, task_workers)
        except Exception as e:
            print(f"[List {list_num+1}/{total_lists}] Error during task creation phase for {list_id}: {e}")

        subtask_futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=task_workers, thread_name_prefix=f"SubtaskPool_L{list_id[:4]}") as subtask_executor:
            for task_id in tasks_created_ids:
                 # Pass task_workers correctly
                 subtask_futures.append(subtask_executor.submit(create_subtasks_for_task, session, base_url, list_id, task_id, num_subtasks, task_workers))
            for future in concurrent.futures.as_completed(subtask_futures):
                try:
                     count = future.result()
                     subtasks_created_count += count
                except Exception as exc:
                     print(f"  Subtask creation future for list {list_id} resulted in error: {exc}")

    list_end_time = time.time()
    list_duration = list_end_time - list_start_time
    # Use total_lists argument here
    print(f"[List {list_num+1}/{total_lists}] DONE List {list_id}. Tasks: {len(tasks_created_ids)}, Subtasks: {subtasks_created_count}. Time: {list_duration:.2f}s")
    return list_id, len(tasks_created_ids), subtasks_created_count

# --- Main Execution ---
if __name__ == "__main__":
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Stress test the TODO API application.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5001", help="Base URL of the TODO API")
    parser.add_argument("-l", "--num-lists", type=int, default=10, help="Number of lists to create")
    parser.add_argument("-t", "--num-tasks", type=int, default=10, help="Number of tasks per list")
    parser.add_argument("-s", "--num-subtasks", type=int, default=2, help="Number of subtasks per task")
    parser.add_argument("--list-workers", type=int, default=5, help="Max concurrent workers for creating lists")
    parser.add_argument("--task-workers", type=int, default=10, help="Max concurrent workers for tasks/subtasks within each list")

    args = parser.parse_args()

    print(f"Stress Test Configuration:")
    print(f" - Target API: {args.base_url}")
    print(f" - Lists to create: {args.num_lists}")
    print(f" - Tasks per list: {args.num_tasks}")
    print(f" - Subtasks per task: {args.num_subtasks}")
    print(f" - List Workers: {args.list_workers}")
    print(f" - Task/Subtask Workers (per list): {args.task_workers}")
    print("-" * 30)

    # --- Test Execution ---
    print("Starting stress test...")
    overall_start_time = time.time()
    total_tasks_created = 0
    total_subtasks_created = 0
    lists_completed_count = 0

    # Primary ThreadPoolExecutor for creating lists
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.list_workers, thread_name_prefix="ListWorker") as executor:
        # Map list creation function to an iterator, passing necessary args
        future_to_list_num = {
            executor.submit(
                create_list_content,
                i,
                args.base_url,
                args.num_tasks,
                args.num_subtasks,
                args.task_workers,
                args.num_lists # Pass total lists for printing
            ): i
            for i in range(args.num_lists)
        }

        for future in concurrent.futures.as_completed(future_to_list_num):
            list_num = future_to_list_num[future]
            try:
                result = future.result()
                if result:
                    list_id, tasks, subtasks = result
                    total_tasks_created += tasks
                    total_subtasks_created += subtasks
                    lists_completed_count += 1
            except Exception as exc:
                print(f"List {list_num+1} main future threw an exception: {exc}")

    overall_end_time = time.time()
    overall_duration = overall_end_time - overall_start_time

    print("-" * 30)
    print("Stress Test Complete")
    print(f" - Overall Duration: {overall_duration:.2f} seconds")
    print(f" - Lists completed: {lists_completed_count}/{args.num_lists}")
    print(f" - Total tasks created: {total_tasks_created}")
    print(f" - Total subtasks created: {total_subtasks_created}")
    print(f" - Average time per list: {overall_duration / lists_completed_count if lists_completed_count > 0 else 'N/A'} seconds")
    print("-" * 30) 