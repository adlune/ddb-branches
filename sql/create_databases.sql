-- drop in case the databases exist (reproducible)

DROP DATABASE IF EXISTS ddb_catalog;
DROP DATABASE IF EXISTS ddb_morelia;
DROP DATABASE IF EXISTS ddb_patzcuaro;

-- create the databases.
-- ddb_catalog is the global catalog which contains the list of nodes (branches).

SET NAMES utf8mb4; -- character set for accents and special characters (e.g. Pátzcuaro)

-- catalog

CREATE DATABASE ddb_catalog CHARACTER SET utf8mb4;
USE ddb_catalog;

CREATE TABLE Nodes (
    Id INT PRIMARY KEY,
    Name VARCHAR(50) NOT NULL UNIQUE,
    Host VARCHAR(100) NOT NULL,
    Port INT NOT NULL DEFAULT 3306,
    DbName VARCHAR(64) NOT NULL
);

INSERT INTO Nodes (Id, Name, Host, Port, DbName) VALUES
    (1, 'Morelia', 'localhost', 3306, 'ddb_morelia'),
    (2, 'Pátzcuaro', 'localhost', 3306, 'ddb_patzcuaro');

-- distributed tables created from the program (horizontal fragmentation by branch).
-- every node has one fragment of each table, so a new node needs the column list to create its own.
-- DistributedColumns.Id keeps the columns in the order they were created.

CREATE TABLE DistributedTables (
    Name VARCHAR(64) PRIMARY KEY
);

CREATE TABLE DistributedColumns (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    TableName VARCHAR(64) NOT NULL,
    Name VARCHAR(64) NOT NULL,
    Type VARCHAR(30) NOT NULL,
    FOREIGN KEY (TableName) REFERENCES DistributedTables(Name)
);


-- morelia node

CREATE DATABASE ddb_morelia CHARACTER SET utf8mb4;
USE ddb_morelia;

CREATE TABLE Clients (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Name VARCHAR(50) NOT NULL,
    PaternalSurname VARCHAR(50) NOT NULL,
    MaternalSurname VARCHAR(50),
    RFC VARCHAR(13) NOT NULL UNIQUE
) AUTO_INCREMENT = 1000001;

CREATE TABLE Addresses (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Street VARCHAR(100) NOT NULL,
    Number VARCHAR(10) NOT NULL,
    Neighborhood VARCHAR(100),
    State VARCHAR(50) NOT NULL,
    ZIPCode CHAR(5) NOT NULL,
    ClientId INT NOT NULL,
    FOREIGN KEY (ClientId) REFERENCES Clients(Id)
) AUTO_INCREMENT = 1000001;


-- pátzcuaro node

CREATE DATABASE ddb_patzcuaro CHARACTER SET utf8mb4;
USE ddb_patzcuaro;

CREATE TABLE Clients (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Name VARCHAR(50) NOT NULL,
    PaternalSurname VARCHAR(50) NOT NULL,
    MaternalSurname VARCHAR(50),
    RFC VARCHAR(13) NOT NULL UNIQUE
) AUTO_INCREMENT = 2000001;

CREATE TABLE Addresses (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Street VARCHAR(100) NOT NULL,
    Number VARCHAR(10) NOT NULL,
    Neighborhood VARCHAR(100),
    State VARCHAR(50) NOT NULL,
    ZIPCode CHAR(5) NOT NULL,
    ClientId INT NOT NULL,
    FOREIGN KEY (ClientId) REFERENCES Clients(Id)
) AUTO_INCREMENT = 2000001;


-- morelia sample data (fictitious). 10 clients, each with one address.

USE ddb_morelia;

INSERT INTO Clients (Name, PaternalSurname, MaternalSurname, RFC) VALUES
    ('Juan', 'López', 'García', 'LOGJ850312AB1'),
    ('María', 'Hernández', 'Ruiz', 'HERM900725QW3'),
    ('Luis', 'Martínez', 'Pérez', 'MAPL880214HT5'),
    ('Sofía', 'Gutiérrez', 'Ramos', 'GURS920530KM8'),
    ('Jorge', 'Castillo', 'Vega', 'CAVJ810911LP2'),
    ('Daniela', 'Ortiz', 'Navarro', 'ORND970103BX4'),
    ('Ricardo', 'Mendoza', 'Ávila', 'MEAR750620CJ7'),
    ('Fernanda', 'Rojas', 'Cruz', 'ROCF990817DN1'),
    ('Alejandro', 'Flores', 'Silva', 'FOSA860429EV6'),
    ('Valeria', 'Torres', 'Medina', 'TOMV010305FR9');

INSERT INTO Addresses (Street, Number, Neighborhood, State, ZIPCode, ClientId) VALUES
    ('Av. Madero Poniente', '450', 'Centro', 'Michoacán', '58000', 1000001),
    ('Calle Aquiles Serdán', '12', 'Chapultepec Sur', 'Michoacán', '58260', 1000002),
    ('Av. Camelinas', '3233', 'Bosque Camelinas', 'Michoacán', '58290', 1000003),
    ('Calle Guillermo Prieto', '87', 'Centro', 'Michoacán', '58000', 1000004),
    ('Av. Acueducto', '1050', 'Vasco de Quiroga', 'Michoacán', '58230', 1000005),
    ('Calle Abasolo', '215-B', 'Centro', 'Michoacán', '58000', 1000006),
    ('Av. Ventura Puente', '640', 'Ventura Puente', 'Michoacán', '58020', 1000007),
    ('Calle Nicolás Bravo', '19', 'Félix Ireta', 'Michoacán', '58070', 1000008),
    ('Av. Siervo de la Nación', '2101', 'Las Américas', 'Michoacán', '58270', 1000009),
    ('Calle Río Lerma', 'S/N', 'Nueva Valladolid', 'Michoacán', '58190', 1000010);


-- pátzcuaro sample data (fictitious). 10 clients, each with one address.

USE ddb_patzcuaro;

INSERT INTO Clients (Name, PaternalSurname, MaternalSurname, RFC) VALUES
    ('Carlos', 'Ramírez', 'Torres', 'RATC780104LK9'),
    ('Ana', 'Sánchez', 'Méndez', 'SAMA950918PZ2'),
    ('Miguel', 'Díaz', 'Herrera', 'DIHM830722GW3'),
    ('Laura', 'Morales', 'Estrada', 'MOEL910115HQ6'),
    ('Fernando', 'Reyes', 'Campos', 'RECF870403JT8'),
    ('Gabriela', 'Vargas', 'Luna', 'VALG940826KS1'),
    ('Roberto', 'Aguilar', 'Soto', 'AUSR800212LM4'),
    ('Patricia', 'Jiménez', 'Núñez', 'JINP760930MD7'),
    ('Eduardo', 'Salazar', 'Pineda', 'SAPE020611NB5'),
    ('Isabel', 'Cortés', 'Ochoa', 'COOI980117PX2');

INSERT INTO Addresses (Street, Number, Neighborhood, State, ZIPCode, ClientId) VALUES
    ('Calle Ponce de León', '8', 'Centro', 'Michoacán', '61600', 2000001),
    ('Av. Lázaro Cárdenas', '215', 'Ibarra', 'Michoacán', '61609', 2000002),
    ('Calle Benigno Serrato', '34', 'Centro', 'Michoacán', '61600', 2000003),
    ('Calle Romero', '12-A', 'Centro', 'Michoacán', '61600', 2000004),
    ('Av. de las Américas', '410', 'Revolución', 'Michoacán', '61606', 2000005),
    ('Calle Terán', '5', 'Centro', 'Michoacán', '61600', 2000006),
    ('Calle Navarrete', '71', 'Ibarra', 'Michoacán', '61609', 2000007),
    ('Calle Arciga', '23', 'Centro', 'Michoacán', '61600', 2000008),
    ('Av. Tangara', 'S/N', 'Tangara', 'Michoacán', '61616', 2000009),
    ('Calle Ahumada', '102', 'San Francisco', 'Michoacán', '61604', 2000010);


-- test queries

SELECT * FROM ddb_catalog.Nodes;

SELECT 'Morelia' AS Branch, c.* FROM ddb_morelia.Clients c;
SELECT 'Pátzcuaro' AS Branch, c.* FROM ddb_patzcuaro.Clients c;

SELECT 'Morelia' AS Branch, a.* FROM ddb_morelia.Addresses a;
SELECT 'Pátzcuaro' AS Branch, a.* FROM ddb_patzcuaro.Addresses a;
