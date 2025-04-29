# Todo App with Redis Backend

A multi-list Todo application built with Flask and NADB, using Redis as the storage backend.

## Docker Setup

This application is containerized and ready to be deployed using Docker. It requires an existing Redis server.

### Configuration

Edit the `.env` file to set your Redis connection parameters:

```
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

1. Make sure Redis is running
2. Install dependencies: `pip install Flask "nadb[redis]"`
3. Run the application: `python todo_app_redis.py`

## Features

- Create multiple todo lists
- Add tasks and subtasks
- Mark tasks as complete
- Delete tasks or entire lists
- Data persistence using Redis backend
- High-performance with in-memory caching 