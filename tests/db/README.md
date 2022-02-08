# Postgres

export CHIA_DB_CONNECTION=postgresql://chia:chia@localhost:54321/full_node_db
docker-compose -f docker-compose-postgres.yml up

To stop the container:

docker-compose -f docker-compose-postgres.yml down --volumes

# MySQL

To run the container:

export CHIA_DB_CONNECTION=mysql+pymysql://chia:chia@localhost:33061/full_node_db
docker-compose -f docker-compose-mysql.yml up

To stop the container:

docker-compose -f docker-compose-mysql.yml down --volumes