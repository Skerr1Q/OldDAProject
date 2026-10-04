CREATE TABLE IF NOT EXISTS Person
(
    person_id character varying(40),
    sex character varying(255),
    birth integer,
    institution_id integer,
    student_type character varying(255),
    class_profile character varying(255),
    class_lang character varying(255),
    location_id integer,
    PRIMARY KEY (person_id)
);

CREATE TABLE IF NOT EXISTS ZnoResult
(
    result_id integer GENERATED ALWAYS AS IDENTITY,
    person_id character varying(40),
    test_name character varying(255),
    test_status character varying(255),
    test_institution integer,
    ball100 real,
    ball12 real,
    ball real,
    adapt_scale character varying(255),
    dpa_level character varying(255),
    exam_year character varying(255),
    test_lang character varying(255),
    PRIMARY KEY (result_id)
);

CREATE TABLE IF NOT EXISTS Location
(
    location_id integer GENERATED ALWAYS AS IDENTITY,
    region character varying(255),
    area character varying(255),
    territory character varying(255),
    PRIMARY KEY (location_id)
);

CREATE TABLE IF NOT EXISTS Institution
(
	institution_id integer GENERATED ALWAYS AS IDENTITY,
    institution_name character varying(255),
    parent_name character varying(255),
    inst_type character varying(255),
    location_id integer,
    PRIMARY KEY (institution_id)
);

CREATE TABLE IF NOT EXISTS Territory
(
    ter_name character varying(255),
    ter_type character varying(255),
    PRIMARY KEY (ter_name)
);

ALTER TABLE ZnoResult
    ADD FOREIGN KEY (person_id)
    REFERENCES Person (person_id);


ALTER TABLE Person
    ADD FOREIGN KEY (institution_id)
    REFERENCES Institution (institution_id);


ALTER TABLE Person
    ADD FOREIGN KEY (location_id)
    REFERENCES Location (location_id);


ALTER TABLE Institution
    ADD FOREIGN KEY (location_id)
    REFERENCES Location (location_id);


ALTER TABLE ZnoResult
    ADD FOREIGN KEY (test_institution)
    REFERENCES Institution (institution_id);


ALTER TABLE Location
    ADD FOREIGN KEY (territory)
    REFERENCES Territory (ter_name);
