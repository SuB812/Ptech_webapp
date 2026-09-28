-- ============================================================================
--  Ptech_webapp -- database / role / extension bootstrap
--  See specs/11-dev-setup.md section 2.2
--
--  ASCII ONLY. Do not add non-ASCII characters to this file.
--  On a Korean Windows console psql uses client_encoding = UHC, so UTF-8
--  Korean bytes in a -f script fail with a UHC/UTF8 conversion error.
--
--  The ptech role password is read from the PTECH_DB_PASSWORD environment
--  variable. It is never stored in this file and never passed on the command
--  line (command lines are visible to other processes).
--
--  Usage (PowerShell):
--    $sec = Read-Host -AsSecureString 'New password for the ptech role'
--    $env:PTECH_DB_PASSWORD = [System.Net.NetworkCredential]::new('', $sec).Password
--    & 'C:\Program Files\PostgreSQL\16\bin\psql.exe' -U postgres -h localhost -f backend\db_init.sql
--    Remove-Item Env:\PTECH_DB_PASSWORD
--
--  psql prompts for the postgres superuser password itself; that prompt works
--  because libpq reads it from the terminal, unlike the \prompt meta-command.
--
--  Do NOT run with -1 / --single-transaction: CREATE DATABASE cannot run
--  inside a transaction block.
--
--  Safe to run more than once (idempotent).
-- ============================================================================

\set ON_ERROR_STOP on

\echo ''
\echo '=== Ptech_webapp database initialization ====================='
\echo ''

-- ---------------------------------------------------------------------------
-- 1. Read the ptech password from the environment.
--    \getenv requires PostgreSQL 13+ (this project targets 16).
-- ---------------------------------------------------------------------------
\getenv ptech_pw PTECH_DB_PASSWORD

\if :{?ptech_pw}
\else
\echo '!! ERROR: environment variable PTECH_DB_PASSWORD is not set.'
\echo ''
\echo '   Set it first, then re-run this script:'
\echo ''
\echo '     $sec = Read-Host -AsSecureString ''New password for the ptech role'''
\echo '     $env:PTECH_DB_PASSWORD = [System.Net.NetworkCredential]::new('''', $sec).Password'
\echo ''
\echo '   Nothing has been changed.'
\quit
\endif

-- Reject an empty or trivially short value. Only a boolean leaves the server;
-- the password itself is never selected or echoed.
SELECT (length(:'ptech_pw') >= 8) AS pw_ok \gset

\if :pw_ok
\else
\echo '!! ERROR: PTECH_DB_PASSWORD must be at least 8 characters.'
\echo '   Nothing has been changed.'
\quit
\endif

\echo '-- password supplied via environment: OK'

-- Keep the password out of the server log in case this cluster runs with
-- log_statement = ddl or all. Session-local; requires superuser (we are
-- connected as postgres).
SET log_statement = 'none';

-- ---------------------------------------------------------------------------
-- 2. Check that the pgvector binary is installed in this cluster.
--    (This machine already has pgvector 0.8.6.)
-- ---------------------------------------------------------------------------
\echo ''
\echo '-- extensions available in this cluster:'
SELECT name,
       default_version,
       coalesce(installed_version, 'not installed') AS installed
FROM pg_available_extensions
WHERE name IN ('vector', 'pg_trgm')
ORDER BY name;

\echo ''
\echo '   If "vector" is missing above, the pgvector binary is not installed.'
\echo '   Do specs/11-dev-setup.md section 2.1 first.'
\echo ''

-- ---------------------------------------------------------------------------
-- 3. Role "ptech".
--    CREATEDB is required: pytest-django creates a test_ptech database.
-- ---------------------------------------------------------------------------
SELECT format('CREATE ROLE ptech WITH LOGIN CREATEDB PASSWORD %L', :'ptech_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ptech')
\gexec

-- If the role already exists, align its password and CREATEDB privilege.
SELECT format('ALTER ROLE ptech WITH LOGIN CREATEDB PASSWORD %L', :'ptech_pw')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ptech')
\gexec

-- Drop the password from the psql session as soon as it is no longer needed.
\unset ptech_pw

\echo '-- role ptech ready'

-- ---------------------------------------------------------------------------
-- 4. Database "ptech".
--
--    If this fails because template1 is not UTF8, use instead:
--      CREATE DATABASE ptech OWNER ptech ENCODING 'UTF8'
--        TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C';
-- ---------------------------------------------------------------------------
SELECT 'CREATE DATABASE ptech OWNER ptech ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'ptech')
\gexec

\echo '-- database ptech ready'

-- ---------------------------------------------------------------------------
-- 5. Extensions must be created inside the ptech database.
--    Creating them in the postgres database does not make them usable here.
--
--    psql reuses the superuser password for \connect, so you should not be
--    prompted again. If you are, enter the postgres password once more.
-- ---------------------------------------------------------------------------
\connect ptech

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

\echo '-- extensions vector and pg_trgm created'

-- ---------------------------------------------------------------------------
-- 6. Schema ownership.
--    PostgreSQL 15+ revoked the default CREATE privilege on schema public, so
--    migrations cannot create tables without this.
-- ---------------------------------------------------------------------------
ALTER SCHEMA public OWNER TO ptech;
GRANT ALL ON SCHEMA public TO ptech;

\echo '-- schema public granted to ptech'

-- ---------------------------------------------------------------------------
-- 7. Extensions in template1, so every NEW database inherits them.
--
--    Why this is required, not optional:
--    pytest-django creates a throwaway test_ptech database as the ptech role
--    and runs the migrations there. pg_trgm is a "trusted" extension, so a
--    non-superuser database owner may install it -- but pgvector's
--    vector.control has no `trusted = true`, so CREATE EXTENSION vector needs
--    superuser. Without this step every database-backed test fails with
--    "permission denied to create extension vector".
--
--    New databases are cloned from template1, so putting the extensions there
--    makes them present before the migration runs, and the migration's
--    CREATE EXTENSION IF NOT EXISTS becomes a no-op that skips before any
--    privilege check.
--
--    NOTE: this is cluster-wide. Every database created on this cluster from
--    now on will carry both extensions. To undo:
--      psql -U postgres -d template1 -c "DROP EXTENSION vector, pg_trgm;"
-- ---------------------------------------------------------------------------
\connect template1

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

\echo '-- template1 extensions (pg_extension is per-database, so check here):'
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm')
ORDER BY extname;

\connect ptech

-- ---------------------------------------------------------------------------
-- 8. Verification
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Result ==================================================='

SELECT current_database() AS database,
       pg_encoding_to_char(encoding) AS encoding
FROM pg_database
WHERE datname = current_database();

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm')
ORDER BY extname;

SELECT rolname, rolcreatedb, rolcanlogin
FROM pg_roles
WHERE rolname = 'ptech';

\echo ''
\echo 'Expected: encoding UTF8, two extension rows, rolcreatedb = t,'
\echo 'plus two extension rows for template1 printed in step 7.'
\echo ''
\echo 'Next steps:'
\echo '  1. Put the same password into POSTGRES_PASSWORD in .env'
\echo '  2. Remove-Item Env:\PTECH_DB_PASSWORD'
\echo '  3. cd backend; .\.venv\Scripts\python.exe manage.py migrate'
\echo '=============================================================='
\echo ''
