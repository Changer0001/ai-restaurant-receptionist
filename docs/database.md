# Database Schema and Models

## ERD (Entity Relationship Diagram)

```
┌─────────────────────────────────────────────────────────────────┐
│                     TENANT MODELS                               │
│  (All include restaurant_id for multi-tenant isolation)         │
│                                                                 │
│  ┌──────────────────────┐      ┌──────────────────────┐        │
│  │   Restaurant         │      │  RestaurantPhone     │        │
│  │                      │◄──────│  Number              │        │
│  │ • id (PK)            │  1:N  │                      │        │
│  │ • name               │      │ • phone_number (U)  │        │
│  │ • timezone           │      │ • twilio_sid        │        │
│  │ • transfer_number    │      │ • is_active         │        │
│  │ • greeting           │      └──────────────────────┘        │
│  └──────────────────────┘                                       │
│         │                                                        │
│    1:N  ├─────────────────────────────────────────┐            │
│         │                                         │             │
│         v                                         v             │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────┐│
│  │ RestaurantHours  │  │ RestaurantFAQ     │  │ Restaurant   ││
│  │                  │  │                   │  │ Knowledge    ││
│  │ • day_of_week    │  │ • question        │  │ Document     ││
│  │ • opening_time   │  │ • answer          │  │              ││
│  │ • closing_time   │  │ • category        │  │ • title      ││
│  │ • is_closed      │  │ • is_active       │  │ • content    ││
│  └──────────────────┘  └───────────────────┘  │ • doc_type   ││
│                                                │ • vector_ids ││
│                                                └──────────────┘│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    OPERATION MODELS                             │
│                                                                 │
│  ┌────────────────────┐      ┌───────────────────┐             │
│  │   Reservation      │      │       Call        │             │
│  │                    │      │                   │             │
│  │ • customer_name    │      │ • call_sid (PK)   │             │
│  │ • customer_phone   │      │ • caller_number   │             │
│  │ • reservation_date │      │ • start_time      │             │
│  │ • party_size       │      │ • duration        │             │
│  │ • status (enum)    │      │ • outcome (enum)  │             │
│  │ • call_sid (FK)    │◄─────│ • transcript      │             │
│  │ • special_notes    │      │ • was_transferred │             │
│  └────────────────────┘      └───────────────────┘             │
│                                       │                         │
│                                   1:N ├──────────────────┐     │
│                                       │                  v     │
│                     ┌─────────────────────────┐  ┌─────────────┤
│                     │ CallTranscript          │  │ CallEvent   │
│                     │                         │  │             │
│                     │ • role (caller/asst)    │  │ • event_type│
│                     │ • message               │  │ • event_data│
│                     │ • timestamp             │  │ • timestamp │
│                     │ • confidence            │  └─────────────┤
│                     └─────────────────────────┘                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   AUTH & AUDIT MODELS                           │
│                                                                 │
│  ┌────────────────────┐      ┌──────────────────┐              │
│  │      User          │      │    AuditLog      │              │
│  │                    │◄─────│                  │              │
│  │ • email (U)        │  1:N │ • user_id (FK)   │              │
│  │ • role (enum)      │      │ • action         │              │
│  │ • restaurant_id FK │      │ • resource_type  │              │
│  │ • is_active        │      │ • resource_id    │              │
│  │ • hashed_password  │      │ • changes (JSON) │              │
│  │ • last_login       │      │ • timestamp      │              │
│  └────────────────────┘      └──────────────────┘              │
│                                                                 │
│  ┌─────────────────────────────────────────────┐               │
│  │          Notification                       │               │
│  │                                             │               │
│  │ • notification_type (sms, email)            │               │
│  │ • recipient (phone or email)                │               │
│  │ • message                                   │               │
│  │ • is_sent                                   │               │
│  │ • error_message                             │               │
│  └─────────────────────────────────────────────┘               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Core Tables

### Restaurant

The primary tenant entity. Everything is scoped to a restaurant.

```sql
CREATE TABLE restaurants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    address VARCHAR(500),
    city VARCHAR(100),
    state VARCHAR(50),
    postal_code VARCHAR(20),
    country VARCHAR(100) DEFAULT 'US',
    phone_number VARCHAR(20) UNIQUE,
    website VARCHAR(500),
    email VARCHAR(255),
    timezone VARCHAR(50) DEFAULT 'America/New_York',
    transfer_number VARCHAR(20),
    menu_url VARCHAR(500),
    ai_greeting TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_restaurants_name ON restaurants(name);
CREATE INDEX idx_restaurants_is_active ON restaurants(is_active);
```

### RestaurantPhoneNumber

Maps Twilio phone numbers to restaurants for incoming call routing.

```sql
CREATE TABLE restaurant_phone_numbers (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    phone_number VARCHAR(20) NOT NULL UNIQUE,
    twilio_sid VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_phone_number ON restaurant_phone_numbers(phone_number);
CREATE INDEX idx_twilio_sid ON restaurant_phone_numbers(twilio_sid);
CREATE INDEX idx_phone_restaurant_id ON restaurant_phone_numbers(restaurant_id);
```

### RestaurantHours

Operating hours per day. Supports holiday hours via separate entries.

```sql
CREATE TABLE restaurant_hours (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    day_of_week INTEGER NOT NULL,  -- 0=Monday, 6=Sunday
    opening_time VARCHAR(5) NOT NULL,  -- HH:MM
    closing_time VARCHAR(5) NOT NULL,  -- HH:MM
    is_closed BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    
    UNIQUE(restaurant_id, day_of_week)
);

CREATE INDEX idx_hours_restaurant_day ON restaurant_hours(restaurant_id, day_of_week);
```

### RestaurantFAQ

FAQ entries for the knowledge base.

```sql
CREATE TABLE restaurant_faqs (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    question VARCHAR(500) NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_faq_restaurant_id ON restaurant_faqs(restaurant_id);
CREATE INDEX idx_faq_category ON restaurant_faqs(category);
CREATE INDEX idx_faq_active ON restaurant_faqs(is_active);
```

### RestaurantKnowledgeDocument

Documents for RAG (stored in PostgreSQL, embedded in ChromaDB/Qdrant).

```sql
CREATE TABLE restaurant_knowledge_documents (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    document_type VARCHAR(50),  -- menu, policy, hours, etc.
    source VARCHAR(500),
    is_active BOOLEAN DEFAULT true,
    vector_ids JSON,  -- ChromaDB document IDs
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_doc_restaurant_id ON restaurant_knowledge_documents(restaurant_id);
CREATE INDEX idx_doc_type ON restaurant_knowledge_documents(document_type);
```

## Operation Tables

### Call

Main call record.

```sql
CREATE TABLE calls (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    call_sid VARCHAR(100) NOT NULL UNIQUE,
    caller_number VARCHAR(20) NOT NULL,
    called_number VARCHAR(20) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    outcome VARCHAR(50) DEFAULT 'UNKNOWN',  -- FAQ_ANSWERED, RESERVATION_CREATED, etc.
    was_transferred BOOLEAN DEFAULT false,
    was_escalated BOOLEAN DEFAULT false,
    transcript TEXT,
    recording_path VARCHAR(500),
    metadata JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_call_restaurant_time ON calls(restaurant_id, start_time);
CREATE INDEX idx_call_sid ON calls(call_sid);
CREATE INDEX idx_call_outcome ON calls(outcome);
```

### CallTranscript

Turn-by-turn conversation log.

```sql
CREATE TABLE call_transcripts (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    call_id UUID NOT NULL REFERENCES calls(id),
    role VARCHAR(20) NOT NULL,  -- 'caller' or 'assistant'
    message TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    confidence FLOAT,  -- STT confidence score
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_transcript_call_id ON call_transcripts(call_id);
CREATE INDEX idx_transcript_time ON call_transcripts(timestamp);
```

### Reservation

Reservation requests from callers.

```sql
CREATE TABLE reservations (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(20) NOT NULL,
    customer_email VARCHAR(255),
    reservation_date TIMESTAMP WITH TIME ZONE NOT NULL,
    reservation_time VARCHAR(5) NOT NULL,  -- HH:MM
    party_size INTEGER NOT NULL,
    special_notes TEXT,
    status VARCHAR(50) DEFAULT 'PENDING',  -- PENDING, CONFIRMED, DECLINED, etc.
    call_sid VARCHAR(100),  -- Link to originating call
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_reservation_restaurant_date ON reservations(restaurant_id, reservation_date);
CREATE INDEX idx_reservation_status ON reservations(status);
CREATE INDEX idx_reservation_phone ON reservations(customer_phone);
```

## Authentication & Audit Tables

### User

User accounts with role-based access.

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL UNIQUE,
    username VARCHAR(100) UNIQUE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'restaurant_staff',
    restaurant_id UUID REFERENCES restaurants(id),
    is_active BOOLEAN DEFAULT true,
    last_login TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_user_email ON users(email);
CREATE INDEX idx_user_restaurant ON users(restaurant_id);
CREATE UNIQUE INDEX idx_user_active ON users(email) WHERE is_active;
```

### AuditLog

All user actions for compliance.

```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id UUID,
    changes JSON,
    ip_address VARCHAR(50),
    user_agent VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_audit_restaurant_time ON audit_logs(restaurant_id, created_at);
CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
```

### Notification

Notification history (SMS/Email).

```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY,
    restaurant_id UUID NOT NULL REFERENCES restaurants(id),
    user_id UUID REFERENCES users(id),
    notification_type VARCHAR(50) NOT NULL,  -- sms, email
    recipient VARCHAR(255) NOT NULL,
    subject VARCHAR(500),
    message TEXT NOT NULL,
    is_sent BOOLEAN DEFAULT false,
    sent_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_notification_restaurant_sent ON notifications(restaurant_id, is_sent);
CREATE INDEX idx_notification_type ON notifications(notification_type);
```

## Multi-Tenant Isolation

Every query MUST filter by `restaurant_id`:

```python
# ✅ CORRECT
result = await session.execute(
    select(Reservation).where(
        (Reservation.restaurant_id == restaurant_id) &
        (Reservation.status == "PENDING")
    )
)

# ❌ WRONG - No restaurant_id filter
result = await session.execute(
    select(Reservation).where(
        Reservation.status == "PENDING"
    )
)
```

This is enforced at the application layer, not database constraints (though constraints are welcome).

## Indexing Strategy

### High-Priority Indexes

- `restaurant_id` on all tenant tables (fast tenant filtering)
- `created_at` for time-based queries
- `status` enums for state machine queries
- Unique constraints on `call_sid`, `phone_number`

### Composite Indexes

- `(restaurant_id, created_at)` for time-series queries
- `(restaurant_id, status)` for call/reservation filtering

## Alembic Migrations

Schema changes are managed via Alembic:

```bash
# Create a migration after model changes
alembic revision --autogenerate -m "Add restaurant timezone"

# Apply migrations
alembic upgrade head

# Downgrade if needed
alembic downgrade -1
```

Migrations are stored in `backend/alembic/versions/`.

## Data Retention Policies

Configurable retention via environment:

```
TRANSCRIPT_RETENTION_DAYS=90
RECORDING_RETENTION_DAYS=30
AUDIT_LOG_RETENTION_DAYS=365
```

Implement cleanup jobs (Phase 5+) to delete expired records.

## Backup Strategy

### Daily Backups

```bash
docker exec restaurant_ai_postgres pg_dump -U restaurantai restaurantai > backup_$(date +%Y%m%d).sql
```

### Restore

```bash
docker exec -i restaurant_ai_postgres psql -U restaurantai restaurantai < backup.sql
```

### Cloud Options

Later phases can use:
- AWS RDS automated backups
- Google Cloud SQL backups
- Managed PostgreSQL services

---

For deployment and monitoring, see [deployment.md](deployment.md).
