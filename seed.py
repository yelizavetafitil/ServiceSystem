"""Seed database with test data."""
import os
from datetime import date, timedelta

from servicesystem.app_factory import create_app
from servicesystem.extensions import db
from servicesystem.models import (
    Contract,
    ContractContentAccess,
    IncidentCategory,
    ObjectCategory,
    Organization,
    Plugin,
    PluginVersion,
    Ticket,
    Tutorial,
    User,
    VideoChapter,
    VideoTutorial,
)
from servicesystem.services.audit import ensure_upload_dir


def seed():
    app = create_app()
    with app.app_context():
        if User.query.filter_by(email="admin@belnipi.by").first():
            print("Database already seeded.")
            return

        orgs_data = [
            ("РУП «Брестэнерго»", "brest"),
            ("РУП «Витебскэнерго»", "vitebsk"),
            ("РУП «Минскэнерго»", "minsk"),
        ]
        orgs = []
        for name, short in orgs_data:
            o = Organization(name=name, short_name=short)
            db.session.add(o)
            orgs.append(o)
        db.session.flush()

        contracts = []
        for i, org in enumerate(orgs):
            c = Contract(
                organization_id=org.id,
                number=f"060-194-{25 + i}",
                signed_at=date(2025, 6, 1),
                service_end_date=date(2026, 4, 15) + timedelta(days=i * 30),
                status="active_warranty" if i < 2 else "active_post_warranty",
                master_login=f"master_{org.short_name}",
                document_url=f"/cabinet/contract",
                notes=f"Договор на сопровождение ЭМСТПН — {org.name}",
            )
            c.set_master_password(f"Master{org.short_name.capitalize()}2026!")
            db.session.add(c)
            contracts.append(c)
        db.session.flush()

        admin = User(email="admin@belnipi.by", full_name="Администратор Системы", position="Системный администратор", role="admin")
        admin.set_password("admin123")
        auditor = User(email="auditor@belnipi.by", full_name="Иванов А.П.", position="Главный инженер проекта", role="auditor")
        auditor.set_password("auditor123")
        executor = User(email="executor@belnipi.by", full_name="Петров С.В.", position="Инженер-разработчик модулей", role="executor")
        executor.set_password("executor123")
        db.session.add_all([admin, auditor, executor])

        customers = [
            ("kozlov@brestenergo.by", "Козлов Д.И.", "Инженер ТЭ", orgs[0], contracts[0]),
            ("sidorov@vitebskenergo.by", "Сидоров М.А.", "Начальник ТС", orgs[1], contracts[1]),
        ]
        for email, name, pos, org, contract in customers:
            u = User(email=email, full_name=name, position=pos, role="customer", organization_id=org.id, contract_id=contract.id)
            u.set_password("customer123")
            db.session.add(u)
        db.session.flush()

        objects = [
            ("Система теплоснабжения", ["Топологическая ошибка", "Проблема с расчётом", "Консультация"]),
            ("Система пароснабжения", ["Топологическая ошибка", "Проблема с расчётом", "Консультация"]),
            ("Сетевой контур теплоисточника", ["Топологическая ошибка", "Проблема с расчётом", "Консультация"]),
            ("Проблема с плагином", ["Сбой при установке", "Выдаёт ошибку", "Консультация"]),
        ]
        for i, (oname, incs) in enumerate(objects):
            oc = ObjectCategory(name=oname, sort_order=i)
            db.session.add(oc)
            db.session.flush()
            for j, iname in enumerate(incs):
                db.session.add(IncidentCategory(object_category_id=oc.id, name=iname, sort_order=j))

        upload_dir = app.config["UPLOAD_FOLDER"]
        ensure_upload_dir(upload_dir, "plugins")
        dummy_plugin = os.path.join(upload_dir, "plugins", "heatcalc_v2.4.1.zip")
        with open(dummy_plugin, "wb") as f:
            f.write(b"PK dummy plugin archive for demo\n")

        plugins_data = [
            ("Модуль теплового расчёта", "heat-calc", "2.4.1", "1.8.0", "3.0.0"),
            ("Плагин топологии сети", "topology-net", "1.2.0", "1.8.0", "3.0.0"),
            ("Экспорт в AutoCAD", "export-autocad", "3.0.2", "2.0.0", "3.0.0"),
        ]
        plugin_ids = []
        for name, slug, ver, minv, maxv in plugins_data:
            p = Plugin(name=name, slug=slug, min_core_version=minv, max_core_version=maxv, current_version=ver)
            db.session.add(p)
            db.session.flush()
            plugin_ids.append(p.id)
            pv = PluginVersion(
                plugin_id=p.id, version=ver, changelog_md=f"## v{ver}\n- Исправлены ошибки расчёта\n- Улучшена совместимость с ядром {minv}–{maxv}",
                stored_name="heatcalc_v2.4.1.zip", original_name=f"{slug}-{ver}.zip", size_bytes=42, is_current=True,
            )
            db.session.add(pv)

        tutorials_data = [
            ("Начало работы с ЭМСТПН", "getting-started", "Общее", "эмотпн, начало",
             "# Начало работы\n\n1. Запустите ядро ЭМСТПН\n2. Откройте проект\n3. Выберите режим расчёта\n\n## Горячие клавиши\n- `F5` — расчёт\n- `Ctrl+S` — сохранение"),
            ("Импорт топологии из GIS", "import-gis", "Топология", "gis, импорт",
             "# Импорт топологии\n\nПошаговая инструкция по загрузке данных из GIS-системы."),
            ("Настройка гидравлического режима", "hydraulic-setup", "Расчёт", "гидравлика",
             "# Гидравлический режим\n\nОписание параметров и типовых ошибок."),
        ]
        tutorial_ids = []
        for title, slug, cat, tags, content in tutorials_data:
            t = Tutorial(title=title, slug=slug, category=cat, tags=tags, content_md=content)
            db.session.add(t)
            db.session.flush()
            tutorial_ids.append(t.id)

        videos_data = [
            ("Обзор интерфейса ЭМСТПН", "interface-overview", "Общее", "https://www.youtube.com/embed/dQw4w9WgXcQ", 600,
             "0|Введение\n60|Панель инструментов\n180|Рабочая область\n360|Расчёт и отчёты"),
            ("Создание сетевого контура", "network-contour", "Топология", "https://www.youtube.com/embed/dQw4w9WgXcQ", 900,
             "0|Создание узлов\n120|Соединение участков\n300|Задание параметров"),
        ]
        video_ids = []
        for title, slug, cat, url, dur, chapters_raw in videos_data:
            v = VideoTutorial(title=title, slug=slug, category=cat, video_url=url, duration_sec=dur, description=f"Видеоинструкция: {title}")
            db.session.add(v)
            db.session.flush()
            video_ids.append(v.id)
            for i, line in enumerate(chapters_raw.split("\n")):
                start, ch_title = line.split("|", 1)
                db.session.add(VideoChapter(video_id=v.id, title=ch_title.strip(), start_sec=int(start), sort_order=i))

        for contract in contracts:
            for pid in plugin_ids:
                db.session.add(ContractContentAccess(contract_id=contract.id, content_type="plugin", content_id=pid))
            for tid in tutorial_ids:
                db.session.add(ContractContentAccess(contract_id=contract.id, content_type="tutorial", content_id=tid))
            for vid in video_ids:
                db.session.add(ContractContentAccess(contract_id=contract.id, content_type="video", content_id=vid))

        from servicesystem.services.sla import compute_deadlines, start_timer1
        oc = ObjectCategory.query.first()
        ic = IncidentCategory.query.filter_by(object_category_id=oc.id).first()
        reaction, resolution = compute_deadlines(3)
        customer = User.query.filter_by(email="kozlov@brestenergo.by").first()
        t1 = Ticket(
            number="T-2026-00001", contract_id=contracts[0].id, author_id=customer.id,
            auditor_id=auditor.id, object_category_id=oc.id, incident_category_id=ic.id,
            priority=3, subject="Ошибка расчёта давления на участке №14", description_md="При расчёте сети котельной №3 давление на участке 14 показывает отрицательное значение.",
            status="new", reaction_deadline=reaction, resolution_deadline=resolution,
        )
        start_timer1(t1)
        db.session.add(t1)

        db.session.commit()
        print("Seed completed successfully!")
        print("\n--- Test accounts ---")
        print("Admin:    admin@belnipi.by / admin123")
        print("Auditor:  auditor@belnipi.by / auditor123")
        print("Executor: executor@belnipi.by / executor123")
        print("Customer: kozlov@brestenergo.by / customer123")
        print("\nMaster keys:")
        for c in contracts:
            print(f"  {c.organization.short_name}: login={c.master_login}, password=Master{c.organization.short_name.capitalize()}2026!")


if __name__ == "__main__":
    seed()
