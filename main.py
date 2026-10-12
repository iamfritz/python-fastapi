import json
from typing import Any, Dict, List, Optional

import asyncpg
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext

from app.config import settings

app = FastAPI(title="Laravel AI FastAPI", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def parse_json_array(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []
    return []


def ensure_json(value: Any) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed
        except (TypeError, ValueError):
            return value
    return value


async def get_db_pool() -> asyncpg.Pool:
    return app.state.pool


async def fetch_all(query: str, params: tuple = ()) -> List[dict]:
    pool = await get_db_pool()
    rows = await pool.fetch(query, *params)
    return [dict(row) for row in rows]


async def fetch_one(query: str, params: tuple = ()) -> Optional[dict]:
    pool = await get_db_pool()
    row = await pool.fetchrow(query, *params)
    return dict(row) if row else None


async def execute(query: str, params: tuple = ()) -> dict:
    pool = await get_db_pool()
    result = await pool.execute(query, *params)
    return {"result": result}


def paginate(items: List[dict], page: int = 1, per_page: int = 6, base_path: str = "/blog") -> dict:
    page = max(1, int(page or 1))
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "data": items[start:end],
        "current_page": page,
        "last_page": total_pages,
        "total": total,
        "per_page": per_page,
        "next_page_url": f"{base_path}?page={page + 1}" if page < total_pages else None,
        "prev_page_url": f"{base_path}?page={page - 1}" if page > 1 else None,
    }


def map_product_row(product: dict, category_override: Optional[dict] = None) -> dict:
    category = category_override or {
        "id": product.get("category_id"),
        "name": product.get("category_name"),
        "slug": product.get("category_slug"),
    }
    return {
        "id": product["id"],
        "slug": product["slug"],
        "title": product["title"],
        "description": product["description"],
        "image": product["image"],
        "sku": product["sku"],
        "price": float(product["price"] or 0),
        "tags": parse_json_array(product.get("tags")),
        "category": category if category and category.get("name") else None,
        "published_at": product["created_at"],
    }


async def get_token_from_header(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail={"message": "Unauthorized"})
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail={"message": "Unauthorized"})
    return token


async def get_current_user(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> dict:
    token = await get_token_from_header(authorization)
    try:
        payload = jwt.decode(token, settings()["jwt_secret"], algorithms=["HS256"])
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail={"message": "Invalid token"}) from exc


def require_roles(*roles: str):
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail={"message": "Forbidden"})
        return user

    return checker


@app.on_event("startup")
async def startup_event() -> None:
    app.state.pool = await asyncpg.create_pool(
        settings()["database_url"],
        min_size=1,
        max_size=10,
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await app.state.pool.close()


@app.get("/api/site")
async def site() -> dict:
    return {
        "name": "Python FastAPI + ReactJs",
        "tagline": "Build faster with a Python FastAPI and a modern Next.js frontend.",
        "hero": {
            "title": "Launch smarter digital experiences.",
            "subtitle": "A clean architecture for modern web products, content sites, and business dashboards.",
        },
        "features": [
            "PythonAPI foundation",
            "Next.js user experience",
            "Content-driven blog pages",
            "Product catalog management",
            "Fast setup and clear structure",
        ],
    }


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/pages")
async def pages() -> List[dict]:
    rows = await fetch_all("SELECT * FROM pages WHERE status = 'published' ORDER BY title ASC")
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "slug": row["slug"],
            "content": row["content"],
            "photo": row["photo"],
            "meta_title": row["meta_title"],
            "meta_description": row["meta_description"],
            "meta_keywords": row["meta_keywords"],
            "meta_fields": ensure_json(row.get("meta_fields")),
        }
        for row in rows
    ]


@app.get("/api/pages/{slug}")
async def page_detail(slug: str) -> dict:
    row = await fetch_one("SELECT * FROM pages WHERE slug = $1 AND status = 'published' LIMIT 1", (slug,))
    if not row:
        raise HTTPException(status_code=404, detail={"message": "Page not found"})
    return {
        "id": row["id"],
        "title": row["title"],
        "slug": row["slug"],
        "content": row["content"],
        "photo": row["photo"],
        "meta_title": row["meta_title"],
        "meta_description": row["meta_description"],
        "meta_keywords": row["meta_keywords"],
        "meta_fields": ensure_json(row.get("meta_fields")),
    }


@app.get("/api/blog")
async def blog(request: Request) -> dict:
    page = max(1, int(request.query_params.get("page", 1) or 1))
    rows = await fetch_all(
        """
        SELECT bp.*, c.name AS category_name, c.slug AS category_slug
        FROM blog_posts bp
        LEFT JOIN categories c ON c.id = bp.category_id
        WHERE bp.status = 'published'
        ORDER BY bp.created_at DESC
        """
    )
    mapped = [
        {
            "id": row["id"],
            "slug": row["slug"],
            "title": row["title"],
            "excerpt": row["excerpt"],
            "photo": row["photo"],
            "published_at": row["created_at"],
            "category": {
                "id": row["category_id"],
                "name": row["category_name"],
                "slug": row["category_slug"],
            } if row.get("category_name") else None,
        }
        for row in rows
    ]
    paged = paginate(mapped, page, 6, "/api/blog")
    return paged


@app.get("/api/blog/{slug}")
async def blog_detail(slug: str) -> dict:
    row = await fetch_one(
        """
        SELECT bp.*, c.name AS category_name, c.slug AS category_slug
        FROM blog_posts bp
        LEFT JOIN categories c ON c.id = bp.category_id
        WHERE bp.slug = $1 AND bp.status = 'published'
        LIMIT 1
        """,
        (slug,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"message": "Post not found"})
    return {
        "title": row["title"],
        "content": row["content"],
        "photo": row["photo"],
        "category": {
            "id": row["category_id"],
            "name": row["category_name"],
            "slug": row["category_slug"],
        } if row.get("category_name") else None,
    }


@app.get("/api/categories")
async def categories() -> List[dict]:
    rows = await fetch_all("SELECT id, name, slug FROM categories ORDER BY name ASC")
    return rows


@app.get("/api/categories/{slug}/blog")
async def category_blog(slug: str, request: Request) -> dict:
    category = await fetch_one("SELECT id, name, slug FROM categories WHERE slug = $1 LIMIT 1", (slug,))
    if not category:
        raise HTTPException(status_code=404, detail={"message": "Category not found"})

    page = max(1, int(request.query_params.get("page", 1) or 1))
    rows = await fetch_all(
        """
        SELECT bp.*, c.name AS category_name, c.slug AS category_slug
        FROM blog_posts bp
        LEFT JOIN categories c ON c.id = bp.category_id
        WHERE bp.category_id = $1 AND bp.status = 'published'
        ORDER BY bp.created_at DESC
        """,
        (category["id"],),
    )
    mapped = [
        {
            "id": row["id"],
            "slug": row["slug"],
            "title": row["title"],
            "excerpt": row["excerpt"],
            "photo": row["photo"],
            "published_at": row["created_at"],
            "category": {
                "id": category["id"],
                "name": category["name"],
                "slug": category["slug"],
            },
        }
        for row in rows
    ]
    paged = paginate(mapped, page, 6, f"/api/categories/{slug}/blog")
    return {
        "category": category,
        **paged,
    }


@app.get("/api/products")
async def products(request: Request) -> dict:
    page = max(1, int(request.query_params.get("page", 1) or 1))
    rows = await fetch_all(
        """
        SELECT p.*, c.name AS category_name, c.slug AS category_slug
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.status = 'published'
        ORDER BY p.created_at DESC
        """
    )
    items = [map_product_row(row) for row in rows]
    return paginate(items, page, 12, "/api/products")


@app.get("/api/products/{slug}")
async def product_detail(slug: str) -> dict:
    row = await fetch_one(
        """
        SELECT p.*, c.name AS category_name, c.slug AS category_slug
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.slug = $1 AND p.status = 'published'
        LIMIT 1
        """,
        (slug,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"message": "Product not found"})
    return {
        "id": row["id"],
        "title": row["title"],
        "slug": row["slug"],
        "description": row["description"],
        "image": row["image"],
        "sku": row["sku"],
        "price": float(row["price"] or 0),
        "tags": parse_json_array(row.get("tags")),
        "custom_fields": parse_json_array(row.get("custom_fields")),
        "variations": parse_json_array(row.get("variations")),
        "category": {
            "id": row["category_id"],
            "name": row["category_name"],
            "slug": row["category_slug"],
        } if row.get("category_name") else None,
    }


@app.get("/api/products/category/{slug}")
async def product_category(slug: str, request: Request) -> dict:
    category = await fetch_one("SELECT id, name, slug FROM categories WHERE slug = $1 LIMIT 1", (slug,))
    if not category:
        raise HTTPException(status_code=404, detail={"message": "Category not found"})

    page = max(1, int(request.query_params.get("page", 1) or 1))
    rows = await fetch_all(
        """
        SELECT p.*, c.name AS category_name, c.slug AS category_slug
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.category_id = $1 AND p.status = 'published'
        ORDER BY p.created_at DESC
        """,
        (category["id"],),
    )
    items = [map_product_row(row, category) for row in rows]
    return {
        "category": category,
        **paginate(items, page, 12, f"/api/products/category/{slug}"),
    }


@app.get("/api/products/tag/{tag}")
async def product_tag(tag: str, request: Request) -> dict:
    normalized = str(tag).strip().lower()
    rows = await fetch_all(
        """
        SELECT p.*, c.name AS category_name, c.slug AS category_slug
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.status = 'published'
        ORDER BY p.created_at DESC
        """
    )
    filtered = []
    for row in rows:
        tag_values = [str(item).strip().lower() for item in parse_json_array(row.get("tags"))]
        if normalized in tag_values:
            filtered.append(row)
    items = [map_product_row(row) for row in filtered]
    page = max(1, int(request.query_params.get("page", 1) or 1))
    return {
        "tag": tag,
        **paginate(items, page, 12, f"/api/products/tag/{tag}"),
    }


@app.get("/api/product-categories")
async def product_categories() -> List[dict]:
    return await fetch_all("SELECT id, name, slug FROM categories ORDER BY name ASC")


@app.get("/api/product-tags")
async def product_tags() -> List[str]:
    rows = await fetch_all("SELECT tags FROM products WHERE status = 'published'")
    values = []
    for row in rows:
        values.extend(parse_json_array(row.get("tags")))
    return sorted({str(value).strip() for value in values if str(value).strip()})


@app.get("/api/products-admin")
async def products_admin(user: dict = Depends(require_roles("admin", "editor"))) -> List[dict]:
    rows = await fetch_all(
        """
        SELECT p.*, c.name AS category_name, c.slug AS category_slug
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        ORDER BY p.id DESC
        """
    )
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "slug": row["slug"],
            "description": row["description"],
            "sku": row["sku"],
            "price": float(row["price"] or 0),
            "status": row["status"],
            "image": row["image"],
            "category_id": row["category_id"],
            "category": {
                "id": row["category_id"],
                "name": row["category_name"],
                "slug": row["category_slug"],
            } if row.get("category_name") else None,
            "tags": parse_json_array(row.get("tags")),
            "custom_fields": parse_json_array(row.get("custom_fields")),
            "variations": parse_json_array(row.get("variations")),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.post("/api/products-admin")
async def create_product(request: Request, user: dict = Depends(require_roles("admin", "editor"))) -> dict:
    payload = await request.json()
    title = payload.get("title")
    slug = payload.get("slug")
    sku = payload.get("sku")
    price = payload.get("price")
    if not title or not slug or not sku or price is None:
        raise HTTPException(status_code=400, detail={"message": "Title, slug, sku and price are required"})
    if await fetch_one("SELECT id FROM products WHERE slug = $1 LIMIT 1", (slug,)):
        raise HTTPException(status_code=409, detail={"message": "Slug already exists"})
    if await fetch_one("SELECT id FROM products WHERE sku = $1 LIMIT 1", (sku,)):
        raise HTTPException(status_code=409, detail={"message": "SKU already exists"})

    result = await fetch_one(
        """
        INSERT INTO products (user_id, category_id, title, slug, description, image, sku, price, tags, custom_fields, variations, status, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), NOW())
        RETURNING *
        """,
        (
            user["id"],
            payload.get("category_id"),
            title,
            slug,
            payload.get("description"),
            payload.get("image"),
            sku,
            float(price),
            json.dumps(payload.get("tags")) if payload.get("tags") is not None else None,
            json.dumps(payload.get("custom_fields")) if payload.get("custom_fields") is not None else None,
            json.dumps(payload.get("variations")) if payload.get("variations") is not None else None,
            payload.get("status", "draft"),
        ),
    )
    return result


@app.put("/api/products-admin/{product_id}")
async def update_product(product_id: int, request: Request, user: dict = Depends(require_roles("admin", "editor"))) -> dict:
    payload = await request.json()
    current = await fetch_one("SELECT * FROM products WHERE id = $1 LIMIT 1", (product_id,))
    if not current:
        raise HTTPException(status_code=404, detail={"message": "Product not found"})

    next_slug = payload.get("slug") or current["slug"]
    if await fetch_one("SELECT id FROM products WHERE slug = $1 AND id != $2 LIMIT 1", (next_slug, product_id)):
        raise HTTPException(status_code=409, detail={"message": "Slug already exists"})

    next_sku = payload.get("sku") or current["sku"]
    if await fetch_one("SELECT id FROM products WHERE sku = $1 AND id != $2 LIMIT 1", (next_sku, product_id)):
        raise HTTPException(status_code=409, detail={"message": "SKU already exists"})

    updated = await fetch_one(
        """
        UPDATE products
        SET category_id = $1,
            title = $2,
            slug = $3,
            description = $4,
            image = $5,
            sku = $6,
            price = $7,
            tags = $8,
            custom_fields = $9,
            variations = $10,
            status = $11,
            updated_at = NOW()
        WHERE id = $12
        RETURNING *
        """,
        (
            payload.get("category_id", current["category_id"]),
            payload.get("title", current["title"]),
            next_slug,
            payload.get("description", current["description"]),
            payload.get("image", current["image"]),
            next_sku,
            float(payload.get("price", current["price"] or 0)),
            json.dumps(payload.get("tags", parse_json_array(current.get("tags")))) if "tags" in payload else current.get("tags"),
            json.dumps(payload.get("custom_fields", parse_json_array(current.get("custom_fields")))) if "custom_fields" in payload else current.get("custom_fields"),
            json.dumps(payload.get("variations", parse_json_array(current.get("variations")))) if "variations" in payload else current.get("variations"),
            payload.get("status", current["status"]),
            product_id,
        ),
    )
    return updated


@app.delete("/api/products-admin/{product_id}")
async def delete_product(product_id: int, user: dict = Depends(require_roles("admin"))) -> dict:
    current = await fetch_one("SELECT * FROM products WHERE id = $1 LIMIT 1", (product_id,))
    if not current:
        raise HTTPException(status_code=404, detail={"message": "Product not found"})
    await execute("DELETE FROM products WHERE id = $1", (product_id,))
    return {"message": "Product deleted successfully"}


@app.get("/api/admin/settings")
async def get_admin_settings() -> dict:
    row = await fetch_one("SELECT * FROM site_settings ORDER BY id ASC LIMIT 1")
    if not row:
        return {
            "site_name": "Laravel AI",
            "site_title": "Laravel AI FastAPI",
            "tagline": "Launch smarter digital experiences.",
            "logo_url": "",
            "favicon_url": "",
            "primary_color": "#22d3ee",
            "secondary_color": "#0f172a",
            "contact_email": "hello@laravelai.dev",
            "contact_phone": "+1 555 013 1900",
        }
    return {
        "site_name": row.get("site_name", "Laravel AI"),
        "site_title": row.get("site_title", "Laravel AI FastAPI"),
        "tagline": row.get("tagline"),
        "logo_url": row.get("logo_url"),
        "favicon_url": row.get("favicon_url"),
        "primary_color": row.get("primary_color", "#22d3ee"),
        "secondary_color": row.get("secondary_color", "#0f172a"),
        "contact_email": row.get("contact_email"),
        "contact_phone": row.get("contact_phone"),
    }


@app.put("/api/admin/settings")
async def save_admin_settings(request: Request, user: dict = Depends(require_roles("admin", "editor"))) -> dict:
    payload = await request.json()
    current = await fetch_one("SELECT * FROM site_settings ORDER BY id ASC LIMIT 1")
    if current:
        row = await fetch_one(
            """
            UPDATE site_settings
            SET site_name = $1,
                site_title = $2,
                tagline = $3,
                logo_url = $4,
                favicon_url = $5,
                primary_color = $6,
                secondary_color = $7,
                contact_email = $8,
                contact_phone = $9,
                updated_at = NOW()
            WHERE id = $10
            RETURNING *
            """,
            (
                payload.get("site_name", current["site_name"]),
                payload.get("site_title", current["site_title"]),
                payload.get("tagline", current.get("tagline")),
                payload.get("logo_url", current.get("logo_url")),
                payload.get("favicon_url", current.get("favicon_url")),
                payload.get("primary_color", current["primary_color"]),
                payload.get("secondary_color", current["secondary_color"]),
                payload.get("contact_email", current.get("contact_email")),
                payload.get("contact_phone", current.get("contact_phone")),
                current["id"],
            ),
        )
    else:
        row = await fetch_one(
            """
            INSERT INTO site_settings (
                site_name, site_title, tagline, logo_url, favicon_url,
                primary_color, secondary_color, contact_email, contact_phone, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
            RETURNING *
            """,
            (
                payload.get("site_name", "Laravel AI"),
                payload.get("site_title", "Laravel AI FastAPI"),
                payload.get("tagline"),
                payload.get("logo_url"),
                payload.get("favicon_url"),
                payload.get("primary_color", "#22d3ee"),
                payload.get("secondary_color", "#0f172a"),
                payload.get("contact_email"),
                payload.get("contact_phone"),
            ),
        )
    return await get_admin_settings()


@app.post("/api/register")
async def register(request: Request) -> dict:
    payload = await request.json()
    name = payload.get("name")
    email = payload.get("email")
    password = payload.get("password")
    role = payload.get("role", "editor")
    if not name or not email or not password:
        raise HTTPException(status_code=400, detail={"message": "Name, email and password are required"})
    if await fetch_one("SELECT id FROM users WHERE email = $1 LIMIT 1", (email,)):
        raise HTTPException(status_code=409, detail={"message": "User already exists"})

    password_hash = pwd_context.hash(password)
    row = await fetch_one(
        """
        INSERT INTO users (name, email, password, role, created_at, updated_at)
        VALUES ($1, $2, $3, $4, NOW(), NOW())
        RETURNING id, name, email, role
        """,
        (name, email, password_hash, role),
    )
    token = jwt.encode({"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"]}, settings()["jwt_secret"], algorithm="HS256")
    return {"user": row, "token": token}


@app.post("/api/login")
async def login(request: Request) -> dict:
    payload = await request.json()
    email = payload.get("email")
    password = payload.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail={"message": "Email and password are required"})

    user = await fetch_one("SELECT * FROM users WHERE email = $1 LIMIT 1", (email,))
    if not user or not pwd_context.verify(password, user["password"]):
        raise HTTPException(status_code=401, detail={"message": "Invalid credentials"})

    token = jwt.encode({"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}, settings()["jwt_secret"], algorithm="HS256")
    return {
        "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]},
        "token": token,
    }


@app.get("/api/user")
async def api_user(user: dict = Depends(get_current_user)) -> dict:
    return {"user": user}


@app.get("/api/posts")
async def posts(user: dict = Depends(require_roles("admin", "editor"))) -> List[dict]:
    rows = await fetch_all(
        """
        SELECT bp.*, u.name AS author_name
        FROM blog_posts bp
        LEFT JOIN users u ON u.id = bp.user_id
        ORDER BY bp.id DESC
        """
    )
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "slug": row["slug"],
            "excerpt": row["excerpt"],
            "content": row["content"],
            "photo": row["photo"],
            "status": row["status"],
            "author": row["author_name"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.get("/api/posts-admin")
async def posts_admin(user: dict = Depends(require_roles("admin", "editor"))) -> List[dict]:
    rows = await fetch_all(
        """
        SELECT bp.*, u.name AS author_name
        FROM blog_posts bp
        LEFT JOIN users u ON u.id = bp.user_id
        ORDER BY bp.id DESC
        """
    )
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "slug": row["slug"],
            "excerpt": row["excerpt"],
            "content": row["content"],
            "photo": row["photo"],
            "category_id": row["category_id"],
            "status": row["status"],
            "author": row["author_name"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.post("/api/posts-admin")
async def create_post_admin(request: Request, user: dict = Depends(require_roles("admin", "editor"))) -> dict:
    payload = await request.json()
    title = payload.get("title")
    slug = payload.get("slug")
    content = payload.get("content")
    if not title or not slug or not content:
        raise HTTPException(status_code=400, detail={"message": "Title, slug and content are required"})
    if await fetch_one("SELECT id FROM blog_posts WHERE slug = $1 LIMIT 1", (slug,)):
        raise HTTPException(status_code=409, detail={"message": "Slug already exists"})

    created = await fetch_one(
        """
        INSERT INTO blog_posts (user_id, category_id, title, slug, excerpt, content, photo, status, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
        RETURNING *
        """,
        (
            user["id"],
            payload.get("category_id"),
            title,
            slug,
            payload.get("excerpt", ""),
            content,
            payload.get("photo"),
            payload.get("status", "draft"),
        ),
    )
    return created


@app.put("/api/posts-admin/{post_id}")
async def update_post_admin(post_id: int, request: Request, user: dict = Depends(require_roles("admin", "editor"))) -> dict:
    payload = await request.json()
    current = await fetch_one("SELECT * FROM blog_posts WHERE id = $1 LIMIT 1", (post_id,))
    if not current:
        raise HTTPException(status_code=404, detail={"message": "Blog post not found"})

    next_slug = payload.get("slug") or current["slug"]
    if await fetch_one("SELECT id FROM blog_posts WHERE slug = $1 AND id != $2 LIMIT 1", (next_slug, post_id)):
        raise HTTPException(status_code=409, detail={"message": "Slug already exists"})

    updated = await fetch_one(
        """
        UPDATE blog_posts
        SET category_id = $1,
            title = $2,
            slug = $3,
            excerpt = $4,
            content = $5,
            photo = $6,
            status = $7,
            updated_at = NOW()
        WHERE id = $8
        RETURNING *
        """,
        (
            payload.get("category_id", current["category_id"]),
            payload.get("title", current["title"]),
            next_slug,
            payload.get("excerpt", current.get("excerpt", "")),
            payload.get("content", current["content"]),
            payload.get("photo", current.get("photo")),
            payload.get("status", current["status"]),
            post_id,
        ),
    )
    return updated


@app.delete("/api/posts-admin/{post_id}")
async def delete_post_admin(post_id: int, user: dict = Depends(require_roles("admin"))) -> dict:
    current = await fetch_one("SELECT * FROM blog_posts WHERE id = $1 LIMIT 1", (post_id,))
    if not current:
        raise HTTPException(status_code=404, detail={"message": "Blog post not found"})
    await execute("DELETE FROM blog_posts WHERE id = $1", (post_id,))
    return {"message": "Blog post deleted successfully"}


@app.post("/api/posts")
async def create_post(request: Request, user: dict = Depends(require_roles("admin", "editor"))) -> dict:
    payload = await request.json()
    title = payload.get("title")
    slug = payload.get("slug")
    content = payload.get("content")
    if not title or not slug or not content:
        raise HTTPException(status_code=400, detail={"message": "Title, slug and content are required"})
    if await fetch_one("SELECT id FROM blog_posts WHERE slug = $1 LIMIT 1", (slug,)):
        raise HTTPException(status_code=409, detail={"message": "Slug already exists"})

    created = await fetch_one(
        """
        INSERT INTO blog_posts (user_id, title, slug, excerpt, content, photo, status, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
        RETURNING *
        """,
        (
            user["id"],
            title,
            slug,
            payload.get("excerpt", ""),
            content,
            payload.get("photo"),
            payload.get("status", "draft"),
        ),
    )
    return created


@app.get("/api/pages-admin")
async def pages_admin(user: dict = Depends(require_roles("admin", "editor"))) -> List[dict]:
    rows = await fetch_all("SELECT * FROM pages ORDER BY id ASC")
    return rows


@app.post("/api/pages-admin")
async def create_page(request: Request, user: dict = Depends(require_roles("admin", "editor"))) -> dict:
    payload = await request.json()
    title = payload.get("title")
    slug = payload.get("slug")
    if not title or not slug:
        raise HTTPException(status_code=400, detail={"message": "Title and slug are required"})
    if await fetch_one("SELECT id FROM pages WHERE slug = $1 LIMIT 1", (slug,)):
        raise HTTPException(status_code=409, detail={"message": "Slug already exists"})

    created = await fetch_one(
        """
        INSERT INTO pages (title, slug, content, photo, status, meta_title, meta_description, meta_keywords, meta_fields, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
        RETURNING *
        """,
        (
            title,
            slug,
            payload.get("content"),
            payload.get("photo"),
            payload.get("status", "draft"),
            payload.get("meta_title"),
            payload.get("meta_description"),
            payload.get("meta_keywords"),
            json.dumps(payload.get("meta_fields")) if payload.get("meta_fields") is not None else None,
        ),
    )
    return created


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=settings()["app_port"], reload=True)
