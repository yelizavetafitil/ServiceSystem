"""Seed database with comprehensive test data for TZ acceptance testing.

Usage:
  python seed.py           # skip if already seeded
  python seed.py --force   # drop all tables and reseed
  docker compose --profile seed run --rm seed
  docker compose --profile seed run --rm seed python seed.py --force
"""
import os
import sys
from datetime import date, timedelta

from sqlalchemy import text

from servicesystem.app_factory import create_app, _setup_audit_triggers
from servicesystem.extensions import db
from servicesystem.models import (
    Contract,
    ContractContentAccess,
    IncidentCategory,
    ObjectCategory,
    ObjectCategoryRouting,
    Organization,
    Plugin,
    PluginVersion,
    Ticket,
    Tutorial,
    User,
    VideoChapter,
    VideoTutorial,
    utcnow,
)
from servicesystem.services.audit import ensure_upload_dir, log_audit, log_ticket_history
from servicesystem.services.sla import compute_deadlines
from servicesystem.services.ticket_workflow import (
    on_assign_executor,
    on_mark_ready,
    on_reject,
    on_resolve,
    on_submit_for_review,
    on_ticket_created,
)


def _reset_db():
    """Drop and recreate schema (works while web container holds idle connections)."""
    db.session.execute(text("DROP SCHEMA public CASCADE"))
    db.session.execute(text("CREATE SCHEMA public"))
    db.session.execute(text("GRANT ALL ON SCHEMA public TO public"))
    db.session.commit()
    db.create_all()
    _setup_audit_triggers()


def seed(force: bool = False):
    app = create_app()
    with app.app_context():
        if User.query.filter_by(email="admin@belnipi.by").first() and not force:
            print("Database already seeded. Use: python seed.py --force")
            return

        if force:
            print("Resetting database...")
            _reset_db()

        today = date.today()

        orgs_data = [
            ("РУП «Брестэнерго»", "brest"),
            ("РУП «Витебскэнерго»", "vitebsk"),
            ("РУП «Минскэнерго»", "minsk"),
            ("РУП «Гомельэнерго»", "gomel"),
        ]
        orgs = []
        for name, short in orgs_data:
            org = Organization(name=name, short_name=short)
            db.session.add(org)
            orgs.append(org)
        db.session.flush()

        contracts_cfg = [
            ("060-194-25", orgs[0], "active_warranty", today + timedelta(days=25), "master_brest"),
            ("060-194-26", orgs[1], "active_post_warranty", date(2027, 8, 1), "master_vitebsk"),
            ("060-194-27", orgs[2], "suspended", date(2027, 6, 1), "master_minsk"),
            ("060-194-28", orgs[3], "terminated", date(2025, 1, 1), "master_gomel"),
        ]
        contracts = []
        for num, org, status, end_date, master_login in contracts_cfg:
            c = Contract(
                organization_id=org.id,
                number=num,
                signed_at=date(2025, 6, 1),
                service_end_date=end_date,
                status=status,
                master_login=master_login,
                master_key_expires_at=end_date if status != "terminated" else date(2025, 1, 1),
                document_url="/cabinet/contract",
                notes=f"Договор на сопровождение ЭМСТПН — {org.name}",
            )
            c.set_master_password(f"Master{org.short_name.capitalize()}2026!")
            db.session.add(c)
            contracts.append(c)
        db.session.flush()

        admin = User(
            email="admin@belnipi.by", full_name="Администратор Системы",
            position="Системный администратор", role="admin",
        )
        admin.set_password("admin123")

        auditor = User(
            email="auditor@belnipi.by", full_name="Иванов А.П.",
            position="Главный инженер проекта (ГИП)", role="auditor",
        )
        auditor.set_password("auditor123")

        executor = User(
            email="executor@belnipi.by", full_name="Петров С.В.",
            position="Инженер-разработчик модулей", role="executor",
        )
        executor.set_password("executor123")

        executor2 = User(
            email="executor2@belnipi.by", full_name="Смирнова Е.К.",
            position="Инженер топологии сетей", role="executor",
        )
        executor2.set_password("executor123")

        db.session.add_all([admin, auditor, executor, executor2])
        db.session.flush()

        customers_cfg = [
            ("kozlov@brestenergo.by", "Козлов Д.И.", "Инженер ТЭ", orgs[0], contracts[0], "+375 29 111-22-33"),
            ("ivanova@brestenergo.by", "Иванова О.С.", "Начальник ПТО", orgs[0], contracts[0], "+375 29 222-33-44"),
            ("sidorov@vitebskenergo.by", "Сидоров М.А.", "Начальник ТС", orgs[1], contracts[1], "+375 29 333-44-55"),
            ("petrov@minskenergo.by", "Петров А.В.", "Инженер-сметчик", orgs[2], contracts[2], "+375 29 444-55-66"),
        ]
        customers = []
        for email, name, pos, org, contract, phone in customers_cfg:
            u = User(
                email=email, full_name=name, position=pos, phone=phone,
                role="customer", organization_id=org.id, contract_id=contract.id,
                pd_consent_at=utcnow(),
            )
            u.set_password("customer123")
            db.session.add(u)
            customers.append(u)
        db.session.flush()

        objects = [
            ("Система теплоснабжения", ["Топологическая ошибка", "Проблема с расчётом", "Консультация"]),
            ("Система пароснабжения", ["Топологическая ошибка", "Проблема с расчётом", "Консультация"]),
            ("Сетевой контур теплоисточника", ["Топологическая ошибка", "Проблема с расчётом", "Консультация"]),
            ("Проблема с плагином", ["Сбой при установке", "Выдаёт ошибку", "Консультация"]),
        ]
        obj_cats = []
        for i, (oname, incs) in enumerate(objects):
            oc = ObjectCategory(name=oname, sort_order=i)
            db.session.add(oc)
            db.session.flush()
            obj_cats.append(oc)
            for j, iname in enumerate(incs):
                db.session.add(IncidentCategory(object_category_id=oc.id, name=iname, sort_order=j))

        for oc in ObjectCategory.query.all():
            db.session.add(ObjectCategoryRouting(
                object_category_id=oc.id,
                auditor_id=auditor.id,
                default_executor_id=executor.id,
            ))

        upload_dir = app.config["UPLOAD_FOLDER"]
        ensure_upload_dir(upload_dir, "plugins")
        dummy_plugin = os.path.join(upload_dir, "plugins", "heatcalc_v2.4.1.zip")
        with open(dummy_plugin, "wb") as f:
            f.write(b"PK dummy plugin archive for demo\n")

        plugins_data = [
            ("Модуль теплового расчёта", "heat-calc", "2.4.1", "2.3.0", "1.8.0", "3.0.0"),
            ("Плагин топологии сети", "topology-net", "1.2.0", None, "1.8.0", "3.0.0"),
            ("Экспорт в AutoCAD", "export-autocad", "3.0.2", None, "2.0.0", "3.0.0"),
            ("Модуль гидравлики", "hydraulic-mod", "1.0.0", None, "2.0.0", "3.0.0"),
            ("Отчёты НТД", "ntd-reports", "1.1.0", None, "1.8.0", "3.0.0"),
        ]
        plugin_ids = []
        for name, slug, ver, old_ver, minv, maxv in plugins_data:
            p = Plugin(
                name=name, slug=slug, min_core_version=minv, max_core_version=maxv,
                current_version=ver,
                description=f"Плагин для ЭМСТПН: {name}",
            )
            db.session.add(p)
            db.session.flush()
            plugin_ids.append(p.id)
            if old_ver:
                db.session.add(PluginVersion(
                    plugin_id=p.id, version=old_ver,
                    changelog_md=f"## v{old_ver}\n- Архивная версия",
                    stored_name="heatcalc_v2.4.1.zip", original_name=f"{slug}-{old_ver}.zip",
                    size_bytes=42, is_current=False, is_archived=True,
                ))
            db.session.add(PluginVersion(
                plugin_id=p.id, version=ver,
                changelog_md=(
                    f"## v{ver}\n- Исправлены ошибки расчёта\n"
                    f"- Совместимость с ядром {minv}–{maxv}\n- Обновлены алгоритмы теплового баланса"
                ),
                stored_name="heatcalc_v2.4.1.zip", original_name=f"{slug}-{ver}.zip",
                size_bytes=42, is_current=True, is_archived=False,
            ))

        tutorials_data = [
            ("Начало работы с ЭМСТПН", "getting-started", "Общее", "эмотпн, начало, интерфейс",
             "# Начало работы\n\n1. Запустите ядро ЭМСТПН\n2. Откройте проект\n3. Выберите режим расчёта\n\n## Горячие клавиши\n- `F5` — расчёт\n- `Ctrl+S` — сохранение"),
            ("Импорт топологии из GIS", "import-gis", "Топология", "gis, импорт, топология",
             "# Импорт топологии\n\nПошаговая инструкция по загрузке данных из GIS-системы.\n\n## Требования\n- Формат Shapefile или GeoJSON"),
            ("Настройка гидравлического режима", "hydraulic-setup", "Расчёт", "гидравлика, расчёт",
             "# Гидравлический режим\n\nОписание параметров и типовых ошибок при расчёте давления."),
            ("Работа с котельными", "boiler-rooms", "Теплоснабжение", "котельная, теплоисточник",
             "# Котельные\n\nМоделирование теплоисточника и присоединение сетевого контура."),
            ("Экспорт отчётов в PDF", "export-pdf", "Отчёты", "отчёт, pdf, экспорт",
             "# Экспорт PDF\n\nФормирование отчётов по результатам расчёта для согласования."),
            ("Устранение отрицательного давления", "fix-negative-pressure", "Типовые ошибки", "давление, ошибка",
             "# Отрицательное давление\n\nПричины и способы устранения при гидравлическом расчёте."),
            ("Демо: таблица ограничений Zulu", "demo-zulu-limits-table", "Примеры оформления", "демо, таблица, zulu",
             """# Ограничения демо-версий (пробный материал)

Пример таблицы с объединёнными ячейками.

<table>
<thead>
<tr><th>Продукт</th><th>Задача</th><th>Ограничение</th></tr>
</thead>
<tbody>
<tr>
<td rowspan="3">ZuluGIS и ZuluXTools</td>
<td>Редактирование векторных слоёв</td>
<td rowspan="2">В каждый слой можно ввести не более 150 объектов</td>
</tr>
<tr><td>Трансформация растров</td></tr>
<tr>
<td>Запись в растр</td>
<td>На растре будут отображены надписи Zulu Demo Version</td>
</tr>
<tr>
<td rowspan="3">ZuluServer</td>
<td>Число соединений</td>
<td>Количество одновременных подключений не более одного</td>
</tr>
<tr><td>Редактирование</td><td>Те же ограничения, что и для ZuluGIS</td></tr>
<tr><td>Веб-службы ZuluServer (WMS/WFS/ZWS)</td><td>250 запросов в сутки</td></tr>
<tr>
<td rowspan="2">ZuluThermo</td>
<td>Наладочный расчёт</td>
<td rowspan="2">Суммарное количество потребителей и обобщённых потребителей в рассчитываемой подсети не должно превышать 15</td>
</tr>
<tr><td>Поверочный расчёт</td></tr>
</tbody>
</table>"""),
        ]
        tutorial_ids = []
        for title, slug, cat, tags, content in tutorials_data:
            t = Tutorial(title=title, slug=slug, category=cat, tags=tags, content_md=content)
            db.session.add(t)
            db.session.flush()
            tutorial_ids.append(t.id)

        videos_data = [
            ("Обзор интерфейса ЭМСТПН", "interface-overview", "Общее",
             "https://www.youtube.com/embed/dQw4w9WgXcQ", 600,
             "0|Введение;Обзор назначения системы\n60|Панель инструментов;Описание главных кнопок\n180|Рабочая область;Работа с топологией\n360|Расчёт и отчёты;Запуск расчёта F5"),
            ("Создание сетевого контура", "network-contour", "Топология",
             "https://www.youtube.com/embed/dQw4w9WgXcQ", 900,
             "0|Создание узлов;Добавление потребителей и источников\n120|Соединение участков;Задание диаметров\n300|Задание параметров;Температурный график"),
            ("Установка плагинов", "plugin-install", "Плагины",
             "https://www.youtube.com/embed/dQw4w9WgXcQ", 480,
             "0|Проверка версии ядра;Совместимость min/max\n90|Установка архива;Путь к каталогу plugins\n240|Проверка работы;Тестовый расчёт"),
        ]
        video_ids = []
        for title, slug, cat, url, dur, chapters_raw in videos_data:
            v = VideoTutorial(
                title=title, slug=slug, category=cat, video_url=url,
                duration_sec=dur, description=f"Видеоинструкция: {title}",
            )
            db.session.add(v)
            db.session.flush()
            video_ids.append(v.id)
            for i, line in enumerate(chapters_raw.split("\n")):
                if "|" not in line:
                    continue
                start, rest = line.split("|", 1)
                if ";" in rest:
                    ch_title, desc = rest.split(";", 1)
                else:
                    ch_title, desc = rest, ""
                db.session.add(VideoChapter(
                    video_id=v.id, title=ch_title.strip(), start_sec=int(start.strip()),
                    description=desc.strip() or None, sort_order=i,
                ))

        brest, vitebsk, minsk, _gomel = contracts
        for pid in plugin_ids[:-1]:
            db.session.add(ContractContentAccess(contract_id=brest.id, content_type="plugin", content_id=pid))
        for tid in tutorial_ids:
            db.session.add(ContractContentAccess(contract_id=brest.id, content_type="tutorial", content_id=tid))
        for vid in video_ids[:2]:
            db.session.add(ContractContentAccess(contract_id=brest.id, content_type="video", content_id=vid))

        for pid in plugin_ids:
            db.session.add(ContractContentAccess(contract_id=vitebsk.id, content_type="plugin", content_id=pid))
        for tid in tutorial_ids:
            db.session.add(ContractContentAccess(contract_id=vitebsk.id, content_type="tutorial", content_id=tid))
        for vid in video_ids:
            db.session.add(ContractContentAccess(contract_id=vitebsk.id, content_type="video", content_id=vid))

        for tid in tutorial_ids[:3]:
            db.session.add(ContractContentAccess(contract_id=minsk.id, content_type="tutorial", content_id=tid))

        oc_heat = obj_cats[0]
        ic_topo = IncidentCategory.query.filter_by(object_category_id=oc_heat.id, name="Топологическая ошибка").first()
        ic_calc = IncidentCategory.query.filter_by(object_category_id=oc_heat.id, name="Проблема с расчётом").first()
        oc_plugin = obj_cats[3]
        ic_plugin = IncidentCategory.query.filter_by(object_category_id=oc_plugin.id, name="Выдаёт ошибку").first()

        def make_ticket(num, customer, contract, oc, ic, priority, subject, desc, status_flow=None, **extra):
            reaction, resolution = compute_deadlines(priority)
            t = Ticket(
                number=num,
                contract_id=contract.id,
                author_id=customer.id,
                auditor_id=auditor.id,
                object_category_id=oc.id,
                incident_category_id=ic.id,
                priority=priority,
                subject=subject,
                description_md=desc,
                reaction_deadline=reaction,
                resolution_deadline=resolution,
            )
            db.session.add(t)
            db.session.flush()
            msg = on_ticket_created(t)
            log_ticket_history(t.id, customer.id, "created", details=f"priority={priority}; {msg}")

            if status_flow == "in_progress":
                t.executor_id = executor.id
                msg = on_assign_executor(t)
                log_ticket_history(t.id, auditor.id, "assign_executor", details=msg)
            elif status_flow == "on_review":
                t.executor_id = executor.id
                on_assign_executor(t)
                t.response_text_md = extra.get("draft_response", "## Черновик ответа\n\nПроблема локализована.")
                msg = on_submit_for_review(t)
                log_ticket_history(t.id, executor.id, "submitted_for_review", details=msg)
            elif status_flow == "ready":
                t.executor_id = executor.id
                on_assign_executor(t)
                t.response_text_md = extra.get("draft_response", "## Ответ готов к выдаче")
                on_submit_for_review(t)
                msg = on_mark_ready(t)
                log_ticket_history(t.id, auditor.id, "marked_ready", details=msg)
            elif status_flow == "resolved":
                t.executor_id = executor.id
                on_assign_executor(t)
                on_submit_for_review(t)
                t.response_text_md = extra.get(
                    "response_text_md",
                    "## Официальный ответ\n\nОшибка устранена. Обновите топологию участка №14 и повторите расчёт.",
                )
                msg = on_resolve(t)
                t.timer1_total_seconds = extra.get("t1", 5400)
                t.timer2_total_seconds = extra.get("t2", 10800)
                log_ticket_history(t.id, auditor.id, "approved", details=msg)
            elif status_flow == "rejected":
                msg = on_reject(t)
                log_ticket_history(t.id, auditor.id, "rejected", details=msg)
            return t

        t_new = make_ticket(
            "Т-2026-00001", customers[0], brest, oc_heat, ic_calc, 3,
            "Ошибка расчёта давления на участке №14",
            "При расчёте сети котельной №3 давление на участке 14 показывает отрицательное значение.\n\n**Ожидаемый результат:** давление > 0.",
        )
        make_ticket(
            "Т-2026-00002", customers[0], brest, oc_heat, ic_topo, 2,
            "Некорректная топология узла №7",
            "Узел №7 не соединён с магистралью после импорта GIS.",
            status_flow="in_progress",
        )
        make_ticket(
            "Т-2026-00003", customers[1], brest, oc_plugin, ic_plugin, 4,
            "Критическая ошибка при запуске плагина heat-calc",
            "Плагин не загружается, ошибка DLL init.",
            status_flow="on_review",
            draft_response="## Анализ\n\nКонфликт версии ядра 1.7.x. Требуется обновление.",
        )
        make_ticket(
            "Т-2026-00004", customers[2], vitebsk, oc_heat, ic_calc, 2,
            "Консультация по температурному графику",
            "Уточнить параметры T1/T2 для режима отопления.",
            status_flow="ready",
        )
        make_ticket(
            "Т-2026-00005", customers[2], vitebsk, oc_heat, ic_topo, 3,
            "Сбой экспорта отчёта в PDF",
            "При формировании отчёта PDF файл пустой.",
            status_flow="resolved",
            t1=7200, t2=14400,
        )
        make_ticket(
            "Т-2026-00006", customers[0], brest, oc_heat, ic_calc, 1,
            "Пожелание: добавить тёмную тему интерфейса",
            "Просим реализовать тёмную тему для работы в ночную смену.",
            status_flow="rejected",
        )

        t_reclassified = make_ticket(
            "Т-2026-00007", customers[0], brest, oc_plugin, ic_plugin, 4,
            "Ошибка импорта zpkg.zip",
            "Архив БД не импортируется после обновления.",
            status_flow="in_progress",
        )
        reason = "Заявка не соответствует критерию «Самый высший»"
        t_reclassified.priority = 2
        t_reclassified.priority_changed = True
        t_reclassified.priority_change_reason = reason
        t_reclassified.reaction_deadline, t_reclassified.resolution_deadline = compute_deadlines(2)
        log_ticket_history(
            t_reclassified.id, auditor.id, "priority_change",
            old_value="4", new_value="2",
            details=f"Аудитор: Иванов А.П. Причина: {reason}",
        )

        log_audit(customers[0].id, "login", details="seed demo")
        log_audit(customers[0].id, "download", "plugin", plugin_ids[0], "version=2.4.1")
        log_audit(customers[0].id, "view", "tutorial", tutorial_ids[0])
        log_audit(auditor.id, "ticket_create", "ticket", t_new.id, "seed")

        db.session.commit()

        print("\n" + "=" * 60)
        print("SEED COMPLETED — ServiceSystem test environment")
        print("=" * 60)
        print("\nURL: http://localhost:8095\n")

        print("--- STAFF ---")
        print("Admin:      admin@belnipi.by / admin123")
        print("Auditor:    auditor@belnipi.by / auditor123")
        print("Executor:   executor@belnipi.by / executor123")
        print("Executor 2: executor2@belnipi.by / executor123")

        print("\n--- CUSTOMERS (password: customer123) ---")
        for u in customers:
            c = db.session.get(Contract, u.contract_id)
            print(f"  {u.email}  ({u.full_name}) — {c.number} [{c.status}]")

        print("\n--- MASTER KEYS (registration) ---")
        for c in contracts:
            if c.status != "terminated":
                org = db.session.get(Organization, c.organization_id)
                print(f"  {org.short_name}: login={c.master_login}, password=Master{org.short_name.capitalize()}2026!")

        print("\n--- TICKETS ---")
        for t in Ticket.query.order_by(Ticket.number).all():
            print(f"  {t.number} [{t.status}] P{t.priority} — {t.subject[:50]}")

        print("\n--- CONTRACT SCENARIOS ---")
        print("  Brest (060-194-25):  active_warranty, expires in ~25 days → expiry banner")
        print("  Vitebsk (060-194-26): active_post_warranty, full content")
        print("  Minsk (060-194-27):  suspended → readonly (no new tickets/plugins)")
        print("  Gomel (060-194-28):  terminated → login blocked")

        print("\nRe-seed: python seed.py --force")
        print("=" * 60)


if __name__ == "__main__":
    seed(force="--force" in sys.argv)
