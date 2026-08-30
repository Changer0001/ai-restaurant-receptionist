-- PostgreSQL Initialization Script
-- Sets up extensions and initial configuration

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search
CREATE EXTENSION IF NOT EXISTS "btree_gin";  -- For composite indexes

-- Create user if not exists
-- Note: User 'restaurantai' should already be created by POSTGRES_USER env var

-- Grant permissions
GRANT USAGE ON SCHEMA public TO restaurantai;
GRANT CREATE ON SCHEMA public TO restaurantai;

-- Set statement timeout to prevent runaway queries
ALTER ROLE restaurantai SET statement_timeout = 30000;  -- 30 seconds

-- Set search path
ALTER ROLE restaurantai SET search_path = public, extensions;

-- Create comment
COMMENT ON DATABASE restaurantai IS 'AI Restaurant Receptionist Database';
