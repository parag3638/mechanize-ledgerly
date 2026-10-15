-- Roles and databases. The superuser password lives only in the grader's environment.
-- ledgerly_migrator owns the schema (DDL); ledgerly_app reads and writes rows, never deletes.
CREATE ROLE ledgerly_migrator LOGIN PASSWORD 'ledgerly_migrator';
CREATE ROLE ledgerly_app LOGIN PASSWORD 'ledgerly_app';

CREATE DATABASE ledgerly OWNER ledgerly_migrator;
CREATE DATABASE ledgerly_test OWNER ledgerly_migrator;

\connect ledgerly
GRANT USAGE ON SCHEMA public TO ledgerly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ledgerly_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO ledgerly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ledgerly_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ledgerly_app;

\connect ledgerly_test
GRANT USAGE ON SCHEMA public TO ledgerly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ledgerly_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO ledgerly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ledgerly_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ledgerly_app;

-- Audit: every statement by the schema owner is logged (log_statement=ddl covers everyone else).
-- log_statement is superuser-only, so neither role can turn this off.
ALTER ROLE ledgerly_migrator SET log_statement = 'all';
