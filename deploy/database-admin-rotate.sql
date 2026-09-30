\set ON_ERROR_STOP on
\getenv rotated_password WHISKY_NEW_DB_PASSWORD
ALTER ROLE whisky PASSWORD :'rotated_password';
