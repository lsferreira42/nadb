# Todo App with NADB Storage

A multi-list Todo application built with Flask and NADB. It can use filesystem storage for local development or Redis for shared deployments.

## Docker Setup

This application is containerized and ready to be deployed using Docker. Redis mode requires an existing Redis server.

### Configuration

Edit the `.env` file to set your Redis connection parameters:

```
NADB_STORAGE_ENGINE=redis  # redis or fs
REDIS_HOST=your-redis-server
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=your-redis-password  # If your Redis requires a password
```

### Building and Running

To build and run the application:

```bash
# Build and start the container
docker-compose up -d

# View logs
docker-compose logs -f
```

The application will be available at http://localhost:5001

### Stopping the Application

```bash
docker-compose down
```

## Development

For local development without Docker:

1. Install dependencies: `pip install Flask nadb`
2. Choose storage with `NADB_STORAGE_ENGINE=fs` or `NADB_STORAGE_ENGINE=redis`
3. For Redis mode, install `pip install "nadb[redis]"` and make sure Redis is running
4. Run the application: `python todo_app_redis.py`

Examples:

```bash
# Filesystem mode, data in ./nadb_data
NADB_STORAGE_ENGINE=fs python todo_app_redis.py

# Redis mode
NADB_STORAGE_ENGINE=redis REDIS_HOST=localhost REDIS_PORT=6379 python todo_app_redis.py
```

## Features

- Create multiple todo lists
- Add tasks and subtasks
- Mark tasks as complete
- Delete tasks or entire lists
- Data persistence using filesystem or Redis backend
- High-performance with in-memory caching 
