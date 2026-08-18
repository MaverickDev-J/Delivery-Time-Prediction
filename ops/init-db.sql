-- Initialize separate logical databases for DeliverIQ microservices
CREATE DATABASE orders_db;
CREATE DATABASE payments_db;
CREATE DATABASE inventory_db;
CREATE DATABASE saga_db;
CREATE DATABASE monitoring_db;

GRANT ALL PRIVILEGES ON DATABASE orders_db TO deliveriq;
GRANT ALL PRIVILEGES ON DATABASE payments_db TO deliveriq;
GRANT ALL PRIVILEGES ON DATABASE inventory_db TO deliveriq;
GRANT ALL PRIVILEGES ON DATABASE saga_db TO deliveriq;
GRANT ALL PRIVILEGES ON DATABASE monitoring_db TO deliveriq;
