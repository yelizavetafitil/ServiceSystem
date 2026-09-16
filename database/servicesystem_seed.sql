--
-- PostgreSQL database dump
--

\restrict S59H5AGUeGhCyBB5HzojOPkm0ocnN9ArCHzLj1G6rdBHBwKkRqLKsuTGAwPpQUA

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: prevent_audit_modification(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_audit_modification() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
            BEGIN
                RAISE EXCEPTION 'Audit records are immutable';
            END;
            $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    user_id integer,
    action character varying(64) NOT NULL,
    resource_type character varying(64),
    resource_id integer,
    details text,
    ip_address character varying(45),
    created_at timestamp with time zone
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: contract_content_access; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contract_content_access (
    id integer NOT NULL,
    contract_id integer NOT NULL,
    content_type character varying(32) NOT NULL,
    content_id integer NOT NULL
);


--
-- Name: contract_content_access_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.contract_content_access_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: contract_content_access_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.contract_content_access_id_seq OWNED BY public.contract_content_access.id;


--
-- Name: contracts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contracts (
    id integer NOT NULL,
    organization_id integer NOT NULL,
    number character varying(64) NOT NULL,
    signed_at date,
    service_end_date date,
    status character varying(32) NOT NULL,
    master_login character varying(64) NOT NULL,
    master_password_hash character varying(255) NOT NULL,
    master_key_expires_at date,
    notes text,
    document_url character varying(512),
    created_at timestamp with time zone
);


--
-- Name: contracts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.contracts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: contracts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.contracts_id_seq OWNED BY public.contracts.id;


--
-- Name: incident_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incident_categories (
    id integer NOT NULL,
    object_category_id integer NOT NULL,
    name character varying(255) NOT NULL,
    sort_order integer,
    is_active boolean
);


--
-- Name: incident_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.incident_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: incident_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.incident_categories_id_seq OWNED BY public.incident_categories.id;


--
-- Name: object_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.object_categories (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    sort_order integer,
    is_active boolean
);


--
-- Name: object_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.object_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: object_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.object_categories_id_seq OWNED BY public.object_categories.id;


--
-- Name: object_category_routing; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.object_category_routing (
    id integer NOT NULL,
    object_category_id integer NOT NULL,
    auditor_id integer NOT NULL,
    default_executor_id integer
);


--
-- Name: object_category_routing_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.object_category_routing_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: object_category_routing_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.object_category_routing_id_seq OWNED BY public.object_category_routing.id;


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    short_name character varying(64),
    created_at timestamp with time zone
);


--
-- Name: organizations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.organizations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: organizations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.organizations_id_seq OWNED BY public.organizations.id;


--
-- Name: plugin_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plugin_versions (
    id integer NOT NULL,
    plugin_id integer NOT NULL,
    version character varying(32) NOT NULL,
    changelog_md text,
    stored_name character varying(512) NOT NULL,
    original_name character varying(512) NOT NULL,
    size_bytes bigint,
    is_current boolean,
    is_archived boolean,
    created_at timestamp with time zone
);


--
-- Name: plugin_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.plugin_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: plugin_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.plugin_versions_id_seq OWNED BY public.plugin_versions.id;


--
-- Name: plugins; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plugins (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(64) NOT NULL,
    description text,
    min_core_version character varying(32),
    max_core_version character varying(32),
    current_version character varying(32),
    is_active boolean,
    created_at timestamp with time zone
);


--
-- Name: plugins_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.plugins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: plugins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.plugins_id_seq OWNED BY public.plugins.id;


--
-- Name: ticket_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ticket_attachments (
    id integer NOT NULL,
    ticket_id integer,
    original_name character varying(512) NOT NULL,
    stored_name character varying(512) NOT NULL,
    mime_type character varying(128),
    size_bytes bigint,
    uploaded_at timestamp with time zone
);


--
-- Name: ticket_attachments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ticket_attachments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ticket_attachments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ticket_attachments_id_seq OWNED BY public.ticket_attachments.id;


--
-- Name: ticket_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ticket_history (
    id integer NOT NULL,
    ticket_id integer NOT NULL,
    user_id integer,
    action character varying(64) NOT NULL,
    old_value text,
    new_value text,
    details text,
    created_at timestamp with time zone
);


--
-- Name: ticket_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ticket_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ticket_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ticket_history_id_seq OWNED BY public.ticket_history.id;


--
-- Name: ticket_response_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ticket_response_files (
    id integer NOT NULL,
    ticket_id integer,
    original_name character varying(512) NOT NULL,
    stored_name character varying(512) NOT NULL,
    mime_type character varying(128),
    size_bytes bigint,
    uploaded_by_id integer,
    uploaded_at timestamp with time zone
);


--
-- Name: ticket_response_files_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ticket_response_files_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ticket_response_files_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ticket_response_files_id_seq OWNED BY public.ticket_response_files.id;


--
-- Name: tickets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tickets (
    id integer NOT NULL,
    number character varying(32) NOT NULL,
    contract_id integer NOT NULL,
    author_id integer NOT NULL,
    auditor_id integer,
    executor_id integer,
    object_category_id integer NOT NULL,
    incident_category_id integer NOT NULL,
    priority integer NOT NULL,
    priority_changed boolean,
    priority_change_reason text,
    subject character varying(120) NOT NULL,
    description_md text NOT NULL,
    status character varying(32) NOT NULL,
    response_text_md text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    reaction_deadline timestamp with time zone,
    resolution_deadline timestamp with time zone,
    timer1_started_at timestamp with time zone,
    timer1_stopped_at timestamp with time zone,
    timer1_total_seconds integer,
    timer2_started_at timestamp with time zone,
    timer2_stopped_at timestamp with time zone,
    timer2_total_seconds integer,
    resolved_at timestamp with time zone
);


--
-- Name: tickets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tickets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tickets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tickets_id_seq OWNED BY public.tickets.id;


--
-- Name: tutorials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tutorials (
    id integer NOT NULL,
    title character varying(512) NOT NULL,
    slug character varying(128) NOT NULL,
    category character varying(128),
    tags character varying(512),
    content_md text NOT NULL,
    is_published boolean,
    created_at timestamp with time zone,
    updated_at timestamp with time zone
);


--
-- Name: tutorials_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tutorials_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tutorials_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tutorials_id_seq OWNED BY public.tutorials.id;


--
-- Name: upload_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.upload_sessions (
    id character varying(64) NOT NULL,
    user_id integer NOT NULL,
    original_name character varying(512) NOT NULL,
    stored_name character varying(512) NOT NULL,
    total_size bigint,
    received_bytes bigint,
    mime_type character varying(128),
    context character varying(32),
    context_id integer,
    completed boolean,
    created_at timestamp with time zone,
    updated_at timestamp with time zone
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    full_name character varying(255) NOT NULL,
    "position" character varying(255),
    phone character varying(32),
    role character varying(32) NOT NULL,
    contract_id integer,
    organization_id integer,
    is_active boolean,
    pd_consent_at timestamp with time zone,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: video_chapters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.video_chapters (
    id integer NOT NULL,
    video_id integer NOT NULL,
    title character varying(512) NOT NULL,
    start_sec integer NOT NULL,
    description text,
    sort_order integer
);


--
-- Name: video_chapters_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.video_chapters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: video_chapters_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.video_chapters_id_seq OWNED BY public.video_chapters.id;


--
-- Name: video_tutorials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.video_tutorials (
    id integer NOT NULL,
    title character varying(512) NOT NULL,
    slug character varying(128) NOT NULL,
    category character varying(128),
    description text,
    video_url character varying(1024),
    video_file character varying(512),
    duration_sec integer,
    is_published boolean,
    created_at timestamp with time zone
);


--
-- Name: video_tutorials_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.video_tutorials_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: video_tutorials_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.video_tutorials_id_seq OWNED BY public.video_tutorials.id;


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: contract_content_access id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_content_access ALTER COLUMN id SET DEFAULT nextval('public.contract_content_access_id_seq'::regclass);


--
-- Name: contracts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts ALTER COLUMN id SET DEFAULT nextval('public.contracts_id_seq'::regclass);


--
-- Name: incident_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incident_categories ALTER COLUMN id SET DEFAULT nextval('public.incident_categories_id_seq'::regclass);


--
-- Name: object_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_categories ALTER COLUMN id SET DEFAULT nextval('public.object_categories_id_seq'::regclass);


--
-- Name: object_category_routing id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_category_routing ALTER COLUMN id SET DEFAULT nextval('public.object_category_routing_id_seq'::regclass);


--
-- Name: organizations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations ALTER COLUMN id SET DEFAULT nextval('public.organizations_id_seq'::regclass);


--
-- Name: plugin_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugin_versions ALTER COLUMN id SET DEFAULT nextval('public.plugin_versions_id_seq'::regclass);


--
-- Name: plugins id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugins ALTER COLUMN id SET DEFAULT nextval('public.plugins_id_seq'::regclass);


--
-- Name: ticket_attachments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_attachments ALTER COLUMN id SET DEFAULT nextval('public.ticket_attachments_id_seq'::regclass);


--
-- Name: ticket_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_history ALTER COLUMN id SET DEFAULT nextval('public.ticket_history_id_seq'::regclass);


--
-- Name: ticket_response_files id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_response_files ALTER COLUMN id SET DEFAULT nextval('public.ticket_response_files_id_seq'::regclass);


--
-- Name: tickets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tickets ALTER COLUMN id SET DEFAULT nextval('public.tickets_id_seq'::regclass);


--
-- Name: tutorials id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tutorials ALTER COLUMN id SET DEFAULT nextval('public.tutorials_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: video_chapters id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.video_chapters ALTER COLUMN id SET DEFAULT nextval('public.video_chapters_id_seq'::regclass);


--
-- Name: video_tutorials id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.video_tutorials ALTER COLUMN id SET DEFAULT nextval('public.video_tutorials_id_seq'::regclass);


--
-- Data for Name: audit_logs; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.audit_logs (id, user_id, action, resource_type, resource_id, details, ip_address, created_at) FROM stdin;
1	5	login	\N	\N	seed demo	\N	2026-09-16 07:37:10.523477+00
2	5	download	plugin	1	version=2.4.1	\N	2026-09-16 07:37:10.523479+00
3	5	view	tutorial	1	\N	\N	2026-09-16 07:37:10.52348+00
4	2	ticket_create	ticket	1	seed	\N	2026-09-16 07:37:10.523481+00
\.


--
-- Data for Name: contract_content_access; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.contract_content_access (id, contract_id, content_type, content_id) FROM stdin;
1	1	plugin	1
2	1	plugin	2
3	1	plugin	3
4	1	plugin	4
5	1	tutorial	1
6	1	tutorial	2
7	1	tutorial	3
8	1	tutorial	4
9	1	tutorial	5
10	1	tutorial	6
11	1	video	1
12	1	video	2
13	2	plugin	1
14	2	plugin	2
15	2	plugin	3
16	2	plugin	4
17	2	plugin	5
18	2	tutorial	1
19	2	tutorial	2
20	2	tutorial	3
21	2	tutorial	4
22	2	tutorial	5
23	2	tutorial	6
24	2	video	1
25	2	video	2
26	2	video	3
27	3	tutorial	1
28	3	tutorial	2
29	3	tutorial	3
\.


--
-- Data for Name: contracts; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.contracts (id, organization_id, number, signed_at, service_end_date, status, master_login, master_password_hash, master_key_expires_at, notes, document_url, created_at) FROM stdin;
1	1	060-194-25	2025-06-01	2026-10-11	active_warranty	master_brest	scrypt:32768:8:1$OYibWG7noKhZShLo$fbc157d23d702b4eeef75c50ea35c44836cc9d5d33950ade8ca9387d280992e66b9997c9accc007306729c37e3ffb0ccc0cdca3effa3b188973e4ceb5fc8a0a8	2026-10-11	Договор на сопровождение ЭМСТПН — РУП «Брестэнерго»	/cabinet/contract	2026-09-16 07:37:09.678309+00
2	2	060-194-26	2025-06-01	2027-08-01	active_post_warranty	master_vitebsk	scrypt:32768:8:1$3NiOKJ5Mn5bxWv5v$d6dbfa8092e6d96e81652b21258192cafcf82f516eb9363c585096e81b0bed165c05f3bfed88600f7e17c09a72398c8c4aec3fcc4505d876afe3f84c9c421b87	2027-08-01	Договор на сопровождение ЭМСТПН — РУП «Витебскэнерго»	/cabinet/contract	2026-09-16 07:37:09.678314+00
3	3	060-194-27	2025-06-01	2027-06-01	suspended	master_minsk	scrypt:32768:8:1$mdNe1lUROWlDaLKk$a3671f31e2dc28caa59b818428efb4789dfca2de465cd961310645d52e795b53995cb9c8145d56cebcb41bda1a4fdbb6ba69f175cf490dddd9ebac1a5efbdf56	2027-06-01	Договор на сопровождение ЭМСТПН — РУП «Минскэнерго»	/cabinet/contract	2026-09-16 07:37:09.678314+00
4	4	060-194-28	2025-06-01	2025-01-01	terminated	master_gomel	scrypt:32768:8:1$xJQcC0dM0ERRBgsd$75c88b89f012baa321fc8cc01ef007bfbfd5f9e102b9632df1393cd2ce4d7755163d947b3addec368259788e6b4439edf886915d480f910bc15999b24cfca076	2025-01-01	Договор на сопровождение ЭМСТПН — РУП «Гомельэнерго»	/cabinet/contract	2026-09-16 07:37:09.678315+00
\.


--
-- Data for Name: incident_categories; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.incident_categories (id, object_category_id, name, sort_order, is_active) FROM stdin;
1	1	Топологическая ошибка	0	t
2	1	Проблема с расчётом	1	t
3	1	Консультация	2	t
4	2	Топологическая ошибка	0	t
5	2	Проблема с расчётом	1	t
6	2	Консультация	2	t
7	3	Топологическая ошибка	0	t
8	3	Проблема с расчётом	1	t
9	3	Консультация	2	t
10	4	Сбой при установке	0	t
11	4	Выдаёт ошибку	1	t
12	4	Консультация	2	t
\.


--
-- Data for Name: object_categories; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.object_categories (id, name, sort_order, is_active) FROM stdin;
1	Система теплоснабжения	0	t
2	Система пароснабжения	1	t
3	Сетевой контур теплоисточника	2	t
4	Проблема с плагином	3	t
\.


--
-- Data for Name: object_category_routing; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.object_category_routing (id, object_category_id, auditor_id, default_executor_id) FROM stdin;
1	1	2	3
2	2	2	3
3	3	2	3
4	4	2	3
\.


--
-- Data for Name: organizations; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.organizations (id, name, short_name, created_at) FROM stdin;
1	РУП «Брестэнерго»	brest	2026-09-16 07:37:09.299219+00
2	РУП «Витебскэнерго»	vitebsk	2026-09-16 07:37:09.299225+00
3	РУП «Минскэнерго»	minsk	2026-09-16 07:37:09.299226+00
4	РУП «Гомельэнерго»	gomel	2026-09-16 07:37:09.299227+00
\.


--
-- Data for Name: plugin_versions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.plugin_versions (id, plugin_id, version, changelog_md, stored_name, original_name, size_bytes, is_current, is_archived, created_at) FROM stdin;
1	1	2.3.0	## v2.3.0\n- Архивная версия	heatcalc_v2.4.1.zip	heat-calc-2.3.0.zip	42	f	t	2026-09-16 07:37:10.446872+00
2	1	2.4.1	## v2.4.1\n- Исправлены ошибки расчёта\n- Совместимость с ядром 1.8.0–3.0.0\n- Обновлены алгоритмы теплового баланса	heatcalc_v2.4.1.zip	heat-calc-2.4.1.zip	42	t	f	2026-09-16 07:37:10.446876+00
3	2	1.2.0	## v1.2.0\n- Исправлены ошибки расчёта\n- Совместимость с ядром 1.8.0–3.0.0\n- Обновлены алгоритмы теплового баланса	heatcalc_v2.4.1.zip	topology-net-1.2.0.zip	42	t	f	2026-09-16 07:37:10.451187+00
4	3	3.0.2	## v3.0.2\n- Исправлены ошибки расчёта\n- Совместимость с ядром 2.0.0–3.0.0\n- Обновлены алгоритмы теплового баланса	heatcalc_v2.4.1.zip	export-autocad-3.0.2.zip	42	t	f	2026-09-16 07:37:10.452988+00
5	4	1.0.0	## v1.0.0\n- Исправлены ошибки расчёта\n- Совместимость с ядром 2.0.0–3.0.0\n- Обновлены алгоритмы теплового баланса	heatcalc_v2.4.1.zip	hydraulic-mod-1.0.0.zip	42	t	f	2026-09-16 07:37:10.454618+00
6	5	1.1.0	## v1.1.0\n- Исправлены ошибки расчёта\n- Совместимость с ядром 1.8.0–3.0.0\n- Обновлены алгоритмы теплового баланса	heatcalc_v2.4.1.zip	ntd-reports-1.1.0.zip	42	t	f	2026-09-16 07:37:10.455576+00
\.


--
-- Data for Name: plugins; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.plugins (id, name, slug, description, min_core_version, max_core_version, current_version, is_active, created_at) FROM stdin;
1	Модуль теплового расчёта	heat-calc	Плагин для ЭМСТПН: Модуль теплового расчёта	1.8.0	3.0.0	2.4.1	t	2026-09-16 07:37:10.441477+00
2	Плагин топологии сети	topology-net	Плагин для ЭМСТПН: Плагин топологии сети	1.8.0	3.0.0	1.2.0	t	2026-09-16 07:37:10.44449+00
3	Экспорт в AutoCAD	export-autocad	Плагин для ЭМСТПН: Экспорт в AutoCAD	2.0.0	3.0.0	3.0.2	t	2026-09-16 07:37:10.450076+00
4	Модуль гидравлики	hydraulic-mod	Плагин для ЭМСТПН: Модуль гидравлики	2.0.0	3.0.0	1.0.0	t	2026-09-16 07:37:10.452344+00
5	Отчёты НТД	ntd-reports	Плагин для ЭМСТПН: Отчёты НТД	1.8.0	3.0.0	1.1.0	t	2026-09-16 07:37:10.454043+00
\.


--
-- Data for Name: ticket_attachments; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.ticket_attachments (id, ticket_id, original_name, stored_name, mime_type, size_bytes, uploaded_at) FROM stdin;
\.


--
-- Data for Name: ticket_history; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.ticket_history (id, ticket_id, user_id, action, old_value, new_value, details, created_at) FROM stdin;
1	1	5	created	\N	\N	priority=3; Статус «Новый». Запущен Таймер №1 (реакция). T1=—; T2=—	2026-09-16 07:37:10.493021+00
2	2	5	created	\N	\N	priority=2; Статус «Новый». Запущен Таймер №1 (реакция). T1=—; T2=—	2026-09-16 07:37:10.499593+00
3	2	2	assign_executor	\N	\N	Статус «В работе». Таймер №1 остановлен, запущен Таймер №2. T1=—; T2=—	2026-09-16 07:37:10.499598+00
4	3	6	created	\N	\N	priority=4; Статус «Новый». Запущен Таймер №1 (реакция). T1=—; T2=—	2026-09-16 07:37:10.505921+00
5	3	3	submitted_for_review	\N	\N	Статус «На проверке». Таймер №2 остановлен, запущен Таймер №1. T1=—; T2=—	2026-09-16 07:37:10.505928+00
6	4	7	created	\N	\N	priority=2; Статус «Новый». Запущен Таймер №1 (реакция). T1=—; T2=—	2026-09-16 07:37:10.510954+00
7	4	2	marked_ready	\N	\N	Статус «Готов к выдаче». Таймер №1 остановлен. T1=—; T2=—	2026-09-16 07:37:10.510959+00
8	5	7	created	\N	\N	priority=3; Статус «Новый». Запущен Таймер №1 (реакция). T1=—; T2=—	2026-09-16 07:37:10.515531+00
9	5	2	approved	\N	\N	Статус «Решено». Таймер №1: —, Таймер №2: —, сумма: —	2026-09-16 07:37:10.515536+00
10	6	5	created	\N	\N	priority=1; Статус «Новый». Запущен Таймер №1 (реакция). T1=—; T2=—	2026-09-16 07:37:10.519849+00
11	6	2	rejected	\N	\N	Статус «Отклонено». T1=—; T2=—	2026-09-16 07:37:10.519854+00
12	7	5	created	\N	\N	priority=4; Статус «Новый». Запущен Таймер №1 (реакция). T1=—; T2=—	2026-09-16 07:37:10.528674+00
13	7	2	assign_executor	\N	\N	Статус «В работе». Таймер №1 остановлен, запущен Таймер №2. T1=—; T2=—	2026-09-16 07:37:10.528679+00
14	7	2	priority_change	4	2	Аудитор: Иванов А.П. Причина: Заявка не соответствует критерию «Самый высший»	2026-09-16 07:37:10.52868+00
\.


--
-- Data for Name: ticket_response_files; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.ticket_response_files (id, ticket_id, original_name, stored_name, mime_type, size_bytes, uploaded_by_id, uploaded_at) FROM stdin;
\.


--
-- Data for Name: tickets; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.tickets (id, number, contract_id, author_id, auditor_id, executor_id, object_category_id, incident_category_id, priority, priority_changed, priority_change_reason, subject, description_md, status, response_text_md, created_at, updated_at, reaction_deadline, resolution_deadline, timer1_started_at, timer1_stopped_at, timer1_total_seconds, timer2_started_at, timer2_stopped_at, timer2_total_seconds, resolved_at) FROM stdin;
1	Т-2026-00001	1	5	2	\N	1	2	3	f	\N	Ошибка расчёта давления на участке №14	При расчёте сети котельной №3 давление на участке 14 показывает отрицательное значение.\n\n**Ожидаемый результат:** давление > 0.	new	\N	2026-09-16 07:37:10.484849+00	2026-09-16 07:37:10.489578+00	2026-09-16 12:37:10.483616+00	2026-09-22 07:37:10.483634+00	2026-09-16 07:37:10.487751+00	\N	0	\N	\N	0	\N
2	Т-2026-00002	1	5	2	3	1	1	2	f	\N	Некорректная топология узла №7	Узел №7 не соединён с магистралью после импорта GIS.	in_progress	\N	2026-09-16 07:37:10.490992+00	2026-09-16 07:37:10.496157+00	2026-09-16 16:37:10.488139+00	2026-09-28 07:37:10.48817+00	2026-09-16 07:37:10.495052+00	2026-09-16 07:37:10.495148+00	0	2026-09-16 07:37:10.495157+00	\N	0	\N
3	Т-2026-00003	1	6	2	3	4	11	4	f	\N	Критическая ошибка при запуске плагина heat-calc	Плагин не загружается, ошибка DLL init.	on_review	## Анализ\n\nКонфликт версии ядра 1.7.x. Требуется обновление.	2026-09-16 07:37:10.497738+00	2026-09-16 07:37:10.502898+00	2026-09-16 10:37:10.495196+00	2026-09-17 11:37:10.495206+00	2026-09-16 07:37:10.50187+00	\N	0	2026-09-16 07:37:10.501829+00	2026-09-16 07:37:10.501858+00	0	\N
4	Т-2026-00004	2	7	2	3	1	2	2	f	\N	Консультация по температурному графику	Уточнить параметры T1/T2 для режима отопления.	ready	## Ответ готов к выдаче	2026-09-16 07:37:10.504381+00	2026-09-16 07:37:10.508659+00	2026-09-16 16:37:10.501944+00	2026-09-28 07:37:10.501975+00	2026-09-16 07:37:10.508035+00	2026-09-16 07:37:10.508047+00	0	2026-09-16 07:37:10.508005+00	2026-09-16 07:37:10.508024+00	0	\N
5	Т-2026-00005	2	7	2	3	1	1	3	f	\N	Сбой экспорта отчёта в PDF	При формировании отчёта PDF файл пустой.	resolved	## Официальный ответ\n\nОшибка устранена. Обновите топологию участка №14 и повторите расчёт.	2026-09-16 07:37:10.509978+00	2026-09-16 07:37:10.513385+00	2026-09-16 12:37:10.50811+00	2026-09-22 07:37:10.508122+00	2026-09-16 07:37:10.512401+00	2026-09-16 07:37:10.512409+00	7200	2026-09-16 07:37:10.512389+00	2026-09-16 07:37:10.512397+00	14400	2026-09-16 07:37:10.512414+00
6	Т-2026-00006	1	5	2	\N	1	2	1	f	\N	Пожелание: добавить тёмную тему интерфейса	Просим реализовать тёмную тему для работы в ночную смену.	rejected	\N	2026-09-16 07:37:10.514552+00	2026-09-16 07:37:10.517608+00	2026-09-16 16:37:10.512454+00	2026-09-28 07:37:10.51247+00	2026-09-16 07:37:10.51666+00	2026-09-16 07:37:10.516749+00	0	\N	\N	0	\N
7	Т-2026-00007	1	5	2	3	4	11	2	t	Заявка не соответствует критерию «Самый высший»	Ошибка импорта zpkg.zip	Архив БД не импортируется после обновления.	in_progress	\N	2026-09-16 07:37:10.51859+00	2026-09-16 07:37:10.527381+00	2026-09-16 16:37:10.521885+00	2026-09-28 07:37:10.521926+00	2026-09-16 07:37:10.52154+00	2026-09-16 07:37:10.521744+00	0	2026-09-16 07:37:10.521761+00	\N	0	\N
\.


--
-- Data for Name: tutorials; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.tutorials (id, title, slug, category, tags, content_md, is_published, created_at, updated_at) FROM stdin;
1	Начало работы с ЭМСТПН	getting-started	Общее	эмотпн, начало, интерфейс	# Начало работы\n\n1. Запустите ядро ЭМСТПН\n2. Откройте проект\n3. Выберите режим расчёта\n\n## Горячие клавиши\n- `F5` — расчёт\n- `Ctrl+S` — сохранение	t	2026-09-16 07:37:10.456901+00	2026-09-16 07:37:10.456905+00
2	Импорт топологии из GIS	import-gis	Топология	gis, импорт, топология	# Импорт топологии\n\nПошаговая инструкция по загрузке данных из GIS-системы.\n\n## Требования\n- Формат Shapefile или GeoJSON	t	2026-09-16 07:37:10.458656+00	2026-09-16 07:37:10.458661+00
3	Настройка гидравлического режима	hydraulic-setup	Расчёт	гидравлика, расчёт	# Гидравлический режим\n\nОписание параметров и типовых ошибок при расчёте давления.	t	2026-09-16 07:37:10.459425+00	2026-09-16 07:37:10.459429+00
4	Работа с котельными	boiler-rooms	Теплоснабжение	котельная, теплоисточник	# Котельные\n\nМоделирование теплоисточника и присоединение сетевого контура.	t	2026-09-16 07:37:10.460101+00	2026-09-16 07:37:10.460105+00
5	Экспорт отчётов в PDF	export-pdf	Отчёты	отчёт, pdf, экспорт	# Экспорт PDF\n\nФормирование отчётов по результатам расчёта для согласования.	t	2026-09-16 07:37:10.460761+00	2026-09-16 07:37:10.460765+00
6	Устранение отрицательного давления	fix-negative-pressure	Типовые ошибки	давление, ошибка	# Отрицательное давление\n\nПричины и способы устранения при гидравлическом расчёте.	t	2026-09-16 07:37:10.461604+00	2026-09-16 07:37:10.461608+00
\.


--
-- Data for Name: upload_sessions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.upload_sessions (id, user_id, original_name, stored_name, total_size, received_bytes, mime_type, context, context_id, completed, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.users (id, email, password_hash, full_name, "position", phone, role, contract_id, organization_id, is_active, pd_consent_at, last_login_at, created_at) FROM stdin;
1	admin@belnipi.by	scrypt:32768:8:1$cSncKFnstpkoROgU$55759e38f110b08dac3829bb139ae102aecd9f7443223238aa08d48517e5f9cbcee6c2c97bc864b50d80f331cead4cbb25a1cade711b7c5be4a1459206207249	Администратор Системы	Системный администратор	\N	admin	\N	\N	t	\N	\N	2026-09-16 07:37:10.051552+00
2	auditor@belnipi.by	scrypt:32768:8:1$YbFlqphvIPQ9Gw1H$d9c6b154a29f925529dbd89ec422f189c1a7dae2ff3f87ae32543b65cfcc3299d5a201a9e2da2fbf104570deab0eac1ed541680f203e571e5bbe262b1615e9ba	Иванов А.П.	Главный инженер проекта (ГИП)	\N	auditor	\N	\N	t	\N	\N	2026-09-16 07:37:10.051557+00
3	executor@belnipi.by	scrypt:32768:8:1$Osyu8Jhs1G28x6FS$b5cf1e1e344b753d8c3aad4665f580e10a741e99e6b28165e0bbcc68e25dcb3c52cdf853a2af27b1b53ce700222a5aed3e2db7fee03700ce6cfcb84f403fe00f	Петров С.В.	Инженер-разработчик модулей	\N	executor	\N	\N	t	\N	\N	2026-09-16 07:37:10.051558+00
4	executor2@belnipi.by	scrypt:32768:8:1$hdkqPvemPqfgbiRE$0482d346c6cd8a8768c7cc7efe25380a4b99b6e2a4a04dcf7267e097b45e9b3ac68e3931661b70b88b5b17a3dbc8d0ca915f955fc7d05b80e50b11eabf1de038	Смирнова Е.К.	Инженер топологии сетей	\N	executor	\N	\N	t	\N	\N	2026-09-16 07:37:10.051559+00
5	kozlov@brestenergo.by	scrypt:32768:8:1$zAknzjtxla4913q7$731484d7468d31f8f683cc63545d529b1845378ac986dcd4515d6b801825249c2921c9ec4ab15338474629217d16607986b78a4e8aa4e86ba880c23879949f36	Козлов Д.И.	Инженер ТЭ	+375 29 111-22-33	customer	1	1	t	2026-09-16 07:37:10.055066+00	\N	2026-09-16 07:37:10.418809+00
6	ivanova@brestenergo.by	scrypt:32768:8:1$H0jwbagZkAr4atQk$ae0e72ae0017fe14c4628aff14db4af4fe8a768148498d0f7d4206cfe10c27c394109e0f4b8964a86414adbb69b219647e47799c376a0176810d2f9fe423503f	Иванова О.С.	Начальник ПТО	+375 29 222-33-44	customer	1	1	t	2026-09-16 07:37:10.145717+00	\N	2026-09-16 07:37:10.418814+00
7	sidorov@vitebskenergo.by	scrypt:32768:8:1$J919a1kCXYKUA058$e9efb08026df0edbcacb190dfdf1111cf97586b62e7bd213ffe2e33b9ff233a5722778ba22b8f72df761fa3a529be38c5ca453d4d50f83405cbb3412c584b7b5	Сидоров М.А.	Начальник ТС	+375 29 333-44-55	customer	2	2	t	2026-09-16 07:37:10.237075+00	\N	2026-09-16 07:37:10.418815+00
8	petrov@minskenergo.by	scrypt:32768:8:1$iuOT5KtHIxW5oRmN$0d6e9735a7f627ef636fc899aa68ca2d86274712aa961adbbc195ad5092f3eb1403d407157adf14b6d502986d274435cbd121d2cb66bbc8c631dcc4d305d2098	Петров А.В.	Инженер-сметчик	+375 29 444-55-66	customer	3	3	t	2026-09-16 07:37:10.328302+00	\N	2026-09-16 07:37:10.418816+00
\.


--
-- Data for Name: video_chapters; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.video_chapters (id, video_id, title, start_sec, description, sort_order) FROM stdin;
1	1	Введение	0	Обзор назначения системы	0
2	1	Панель инструментов	60	Описание главных кнопок	1
3	1	Рабочая область	180	Работа с топологией	2
4	1	Расчёт и отчёты	360	Запуск расчёта F5	3
5	2	Создание узлов	0	Добавление потребителей и источников	0
6	2	Соединение участков	120	Задание диаметров	1
7	2	Задание параметров	300	Температурный график	2
8	3	Проверка версии ядра	0	Совместимость min/max	0
9	3	Установка архива	90	Путь к каталогу plugins	1
10	3	Проверка работы	240	Тестовый расчёт	2
\.


--
-- Data for Name: video_tutorials; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.video_tutorials (id, title, slug, category, description, video_url, video_file, duration_sec, is_published, created_at) FROM stdin;
1	Обзор интерфейса ЭМСТПН	interface-overview	Общее	Видеоинструкция: Обзор интерфейса ЭМСТПН	https://www.youtube.com/embed/dQw4w9WgXcQ	\N	600	t	2026-09-16 07:37:10.462975+00
2	Создание сетевого контура	network-contour	Топология	Видеоинструкция: Создание сетевого контура	https://www.youtube.com/embed/dQw4w9WgXcQ	\N	900	t	2026-09-16 07:37:10.465759+00
3	Установка плагинов	plugin-install	Плагины	Видеоинструкция: Установка плагинов	https://www.youtube.com/embed/dQw4w9WgXcQ	\N	480	t	2026-09-16 07:37:10.470293+00
\.


--
-- Name: audit_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.audit_logs_id_seq', 4, true);


--
-- Name: contract_content_access_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.contract_content_access_id_seq', 29, true);


--
-- Name: contracts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.contracts_id_seq', 4, true);


--
-- Name: incident_categories_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.incident_categories_id_seq', 12, true);


--
-- Name: object_categories_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.object_categories_id_seq', 4, true);


--
-- Name: object_category_routing_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.object_category_routing_id_seq', 4, true);


--
-- Name: organizations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.organizations_id_seq', 4, true);


--
-- Name: plugin_versions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.plugin_versions_id_seq', 6, true);


--
-- Name: plugins_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.plugins_id_seq', 5, true);


--
-- Name: ticket_attachments_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.ticket_attachments_id_seq', 1, false);


--
-- Name: ticket_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.ticket_history_id_seq', 14, true);


--
-- Name: ticket_response_files_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.ticket_response_files_id_seq', 1, false);


--
-- Name: tickets_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.tickets_id_seq', 7, true);


--
-- Name: tutorials_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.tutorials_id_seq', 6, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.users_id_seq', 8, true);


--
-- Name: video_chapters_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.video_chapters_id_seq', 10, true);


--
-- Name: video_tutorials_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.video_tutorials_id_seq', 3, true);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: contract_content_access contract_content_access_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_content_access
    ADD CONSTRAINT contract_content_access_pkey PRIMARY KEY (id);


--
-- Name: contracts contracts_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts
    ADD CONSTRAINT contracts_number_key UNIQUE (number);


--
-- Name: contracts contracts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts
    ADD CONSTRAINT contracts_pkey PRIMARY KEY (id);


--
-- Name: incident_categories incident_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incident_categories
    ADD CONSTRAINT incident_categories_pkey PRIMARY KEY (id);


--
-- Name: object_categories object_categories_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_categories
    ADD CONSTRAINT object_categories_name_key UNIQUE (name);


--
-- Name: object_categories object_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_categories
    ADD CONSTRAINT object_categories_pkey PRIMARY KEY (id);


--
-- Name: object_category_routing object_category_routing_object_category_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_category_routing
    ADD CONSTRAINT object_category_routing_object_category_id_key UNIQUE (object_category_id);


--
-- Name: object_category_routing object_category_routing_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_category_routing
    ADD CONSTRAINT object_category_routing_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: plugin_versions plugin_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugin_versions
    ADD CONSTRAINT plugin_versions_pkey PRIMARY KEY (id);


--
-- Name: plugins plugins_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugins
    ADD CONSTRAINT plugins_pkey PRIMARY KEY (id);


--
-- Name: plugins plugins_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugins
    ADD CONSTRAINT plugins_slug_key UNIQUE (slug);


--
-- Name: ticket_attachments ticket_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_attachments
    ADD CONSTRAINT ticket_attachments_pkey PRIMARY KEY (id);


--
-- Name: ticket_history ticket_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_history
    ADD CONSTRAINT ticket_history_pkey PRIMARY KEY (id);


--
-- Name: ticket_response_files ticket_response_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_response_files
    ADD CONSTRAINT ticket_response_files_pkey PRIMARY KEY (id);


--
-- Name: tickets tickets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tickets
    ADD CONSTRAINT tickets_pkey PRIMARY KEY (id);


--
-- Name: tutorials tutorials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tutorials
    ADD CONSTRAINT tutorials_pkey PRIMARY KEY (id);


--
-- Name: tutorials tutorials_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tutorials
    ADD CONSTRAINT tutorials_slug_key UNIQUE (slug);


--
-- Name: upload_sessions upload_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upload_sessions
    ADD CONSTRAINT upload_sessions_pkey PRIMARY KEY (id);


--
-- Name: contract_content_access uq_contract_content; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_content_access
    ADD CONSTRAINT uq_contract_content UNIQUE (contract_id, content_type, content_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: video_chapters video_chapters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.video_chapters
    ADD CONSTRAINT video_chapters_pkey PRIMARY KEY (id);


--
-- Name: video_tutorials video_tutorials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.video_tutorials
    ADD CONSTRAINT video_tutorials_pkey PRIMARY KEY (id);


--
-- Name: video_tutorials video_tutorials_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.video_tutorials
    ADD CONSTRAINT video_tutorials_slug_key UNIQUE (slug);


--
-- Name: ix_audit_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_created_at ON public.audit_logs USING btree (created_at);


--
-- Name: ix_audit_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_user_id ON public.audit_logs USING btree (user_id);


--
-- Name: ix_ticket_history_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ticket_history_created_at ON public.ticket_history USING btree (created_at);


--
-- Name: ix_ticket_history_ticket_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ticket_history_ticket_id ON public.ticket_history USING btree (ticket_id);


--
-- Name: ix_tickets_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tickets_number ON public.tickets USING btree (number);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: audit_logs trg_immutable_audit_logs; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_immutable_audit_logs BEFORE DELETE OR UPDATE ON public.audit_logs FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_modification();


--
-- Name: ticket_history trg_immutable_ticket_history; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_immutable_ticket_history BEFORE DELETE OR UPDATE ON public.ticket_history FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_modification();


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: contract_content_access contract_content_access_contract_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contract_content_access
    ADD CONSTRAINT contract_content_access_contract_id_fkey FOREIGN KEY (contract_id) REFERENCES public.contracts(id);


--
-- Name: contracts contracts_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts
    ADD CONSTRAINT contracts_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: incident_categories incident_categories_object_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incident_categories
    ADD CONSTRAINT incident_categories_object_category_id_fkey FOREIGN KEY (object_category_id) REFERENCES public.object_categories(id);


--
-- Name: object_category_routing object_category_routing_auditor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_category_routing
    ADD CONSTRAINT object_category_routing_auditor_id_fkey FOREIGN KEY (auditor_id) REFERENCES public.users(id);


--
-- Name: object_category_routing object_category_routing_default_executor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_category_routing
    ADD CONSTRAINT object_category_routing_default_executor_id_fkey FOREIGN KEY (default_executor_id) REFERENCES public.users(id);


--
-- Name: object_category_routing object_category_routing_object_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_category_routing
    ADD CONSTRAINT object_category_routing_object_category_id_fkey FOREIGN KEY (object_category_id) REFERENCES public.object_categories(id);


--
-- Name: plugin_versions plugin_versions_plugin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugin_versions
    ADD CONSTRAINT plugin_versions_plugin_id_fkey FOREIGN KEY (plugin_id) REFERENCES public.plugins(id);


--
-- Name: ticket_attachments ticket_attachments_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_attachments
    ADD CONSTRAINT ticket_attachments_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.tickets(id);


--
-- Name: ticket_history ticket_history_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_history
    ADD CONSTRAINT ticket_history_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.tickets(id);


--
-- Name: ticket_history ticket_history_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_history
    ADD CONSTRAINT ticket_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: ticket_response_files ticket_response_files_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_response_files
    ADD CONSTRAINT ticket_response_files_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.tickets(id);


--
-- Name: ticket_response_files ticket_response_files_uploaded_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ticket_response_files
    ADD CONSTRAINT ticket_response_files_uploaded_by_id_fkey FOREIGN KEY (uploaded_by_id) REFERENCES public.users(id);


--
-- Name: tickets tickets_auditor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tickets
    ADD CONSTRAINT tickets_auditor_id_fkey FOREIGN KEY (auditor_id) REFERENCES public.users(id);


--
-- Name: tickets tickets_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tickets
    ADD CONSTRAINT tickets_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.users(id);


--
-- Name: tickets tickets_contract_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tickets
    ADD CONSTRAINT tickets_contract_id_fkey FOREIGN KEY (contract_id) REFERENCES public.contracts(id);


--
-- Name: tickets tickets_executor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tickets
    ADD CONSTRAINT tickets_executor_id_fkey FOREIGN KEY (executor_id) REFERENCES public.users(id);


--
-- Name: tickets tickets_incident_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tickets
    ADD CONSTRAINT tickets_incident_category_id_fkey FOREIGN KEY (incident_category_id) REFERENCES public.incident_categories(id);


--
-- Name: tickets tickets_object_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tickets
    ADD CONSTRAINT tickets_object_category_id_fkey FOREIGN KEY (object_category_id) REFERENCES public.object_categories(id);


--
-- Name: upload_sessions upload_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upload_sessions
    ADD CONSTRAINT upload_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: users users_contract_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_contract_id_fkey FOREIGN KEY (contract_id) REFERENCES public.contracts(id);


--
-- Name: users users_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: video_chapters video_chapters_video_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.video_chapters
    ADD CONSTRAINT video_chapters_video_id_fkey FOREIGN KEY (video_id) REFERENCES public.video_tutorials(id);


--
-- PostgreSQL database dump complete
--

\unrestrict S59H5AGUeGhCyBB5HzojOPkm0ocnN9ArCHzLj1G6rdBHBwKkRqLKsuTGAwPpQUA

