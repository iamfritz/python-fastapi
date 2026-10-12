# Laravel AI FastAPI PostgreSQL API

This project mirrors the existing Laravel API contract for the public site, blog, pages, product catalog, and admin endpoints while using PostgreSQL and FastAPI.

## Setup

1. Start PostgreSQL:

   ```bash
   docker compose up -d
   ```

2. Create a local `.env` file from `.env.example` and update the connection details if needed.

3. Install dependencies:

   ```bash
   pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt
   ```

4. Run the API:

   ```bash
   uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```

5. If you want a fresh PostgreSQL schema, run the SQL in [database/schema.sql](database/schema.sql).

6. Seed the catalog and 20 sample blog posts. The database must have at least one user to use as the posts' author:

   ```bash
   psql -h 127.0.0.1 -U postgres -d laravel_api_ai -f database/seed.sql
   ```

## Included endpoints

The app keeps the same route structure as the Laravel API:

- `/api/site`
- `/api/pages`
- `/api/pages/{slug}`
- `/api/blog`
- `/api/blog/{slug}`
- `/api/categories`
- `/api/categories/{slug}/blog`
- `/api/products`
- `/api/products/{slug}`
- `/api/products/category/{slug}`
- `/api/products/tag/{tag}`
- `/api/product-categories`
- `/api/product-tags`
- `/api/register`
- `/api/login`
- `/api/user`
- `/api/products-admin`
- `/api/posts`
- `/api/pages-admin`

Use the same JWT Bearer token flow as the Laravel API.
