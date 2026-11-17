"""Auftrag mit Stufen (V0 §4.3): Kandidaten -> Auswahl des Betreibers -> Fertigstellen."""

from __future__ import annotations

import hashlib
import io
import shutil

import pytest
from PIL import Image

from darkfluenzer.config import project_root
from darkfluenzer.core import orders
from darkfluenzer.media import models, pipeline
from darkfluenzer.store import Store, StoreError


@pytest.fixture
def setup(cfg):
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    store = Store(cfg.local)
    yield cfg, store, models.load_manifest(cfg.root)
    store.close()


def _finish(
    cfg, store: Store, job_id: int, ok: bool = True, color: int | None = None
) -> int | None:
    """Job so abschließen, wie es der Renderweg tut (Ausgabe in der Galerie, dann Status)."""
    store.set_job_status(job_id, "running")
    if not ok:
        store.set_job_status(job_id, "failed", error="ComfyUI-Fehler")
        orders.advance_order(store, job_id)
        return None
    rel = f"evaluation/test/job{job_id}.png"
    (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (color if color is not None else job_id * 40 % 255, 10, 10)).save(
        cfg.local / rel
    )
    sha = hashlib.sha256((cfg.local / rel).read_bytes()).hexdigest()
    out = {"path": rel, "sha256": sha, "size": (cfg.local / rel).stat().st_size}
    media = pipeline.register_outputs(store, job_id, [out])  # wie run_render
    store.set_job_status(job_id, "done", outputs=[out])
    orders.advance_order(store, job_id)
    return media


def _command(name: str) -> dict:
    return {"request_id": name, "payload_sha": "0" * 64, "command": name, "status": "accepted"}


def test_candidates_selection_and_finish(setup):
    cfg, store, man = setup
    values = {"prompt": "portrait", "seed": 4294967294}
    order_no, jobs = orders.create_order(
        store,
        man,
        "lustify_sdxl_t2i",
        values,
        {},
        count=3,
        finish_workflow="lustify_sdxl_refine",
        command=_command("c1"),
    )
    assert [store.job(j)["params"]["seed"] for j in jobs] == [4294967294, 4294967295, 0]
    assert store.command("c1")["status"] == "completed"
    order = store.order(order_no)
    assert order.source == "operator" and order.customer_id is None and order.status == "producing"

    first = _finish(cfg, store, jobs[0])
    _finish(cfg, store, jobs[1], ok=False)
    (stage,) = store.stages(order.id)
    assert stage.status == "running"  # ein Kandidat läuft noch
    third = _finish(cfg, store, jobs[2])
    assert store.stages(order.id)[0].status == "waiting"

    with pytest.raises(pipeline.PipelineError, match="kein Kandidat"):
        orders.select_candidate(cfg, store, man, order_no, 999, _command("bad"))
    (finish_job,) = orders.select_candidate(cfg, store, man, order_no, third, _command("s1"))
    done, finishing = store.stages(order.id)
    assert done.status == "done" and done.selected_media_id == third != first
    assert finishing.kind == "finish" and finishing.status == "running"
    job = store.job(finish_job)
    assert job["workflow"] == "lustify_sdxl_refine" and job["parent_media_id"] == third
    with pytest.raises(pipeline.PipelineError, match="wartet nicht"):
        orders.select_candidate(cfg, store, man, order_no, first, _command("s2"))

    _finish(cfg, store, finish_job)
    assert store.stages(order.id)[1].status == "done"
    assert store.order(order_no).status == "review" and store.active_orders() == []


def test_failed_stage_retry_has_a_limit(setup):
    cfg, store, man = setup
    order_no, jobs = orders.create_order(
        store, man, "lustify_sdxl_t2i", {"prompt": "p"}, {}, count=2
    )
    for job in jobs:
        _finish(cfg, store, job, ok=False)
    (stage,) = store.stages(store.order(order_no).id)
    assert stage.status == "failed" and stage.error == "ComfyUI-Fehler"
    again = orders.retry_stage(store, man, order_no, 1, 2, _command("r1"))
    assert len(again) == 2 and store.stages(stage.order_id)[0].attempts == 2
    for job in again:
        _finish(cfg, store, job, ok=False)
    with pytest.raises(pipeline.PipelineError, match="höchstens 2"):
        orders.retry_stage(store, man, order_no, 1, 2, _command("r2"))


def test_order_rules(setup):
    _, store, man = setup
    with pytest.raises(pipeline.PipelineError, match="kein Kandidatenauftrag"):
        orders.create_order(store, man, "lustify_sdxl_lora_train", {}, {}, count=1)
    with pytest.raises(pipeline.PipelineError, match="braucht zusätzlich"):
        orders.create_order(
            store,
            man,
            "lustify_sdxl_t2i",
            {"prompt": "p"},
            {},
            count=1,
            finish_workflow="lustify_sam31_edit",
        )
    with pytest.raises(StoreError):
        store.create_production_order("customer", "image", "x")


def test_bit_identical_result_counts_as_candidate(setup):
    """BUG-064: liefert ein Kandidat dieselben Bytes wie ein vorhandenes Medium, zählt dieses als
    sein Ergebnis – statt „kein Ergebnis“."""
    cfg, store, man = setup
    order_no, jobs = orders.create_order(
        store, man, "lustify_sdxl_t2i", {"prompt": "p", "seed": 1}, {}, count=2,
        command=_command("bitgleich"),
    )  # fmt: skip
    first = _finish(cfg, store, jobs[0], color=77)
    second = _finish(cfg, store, jobs[1], color=77)  # bitgleich
    assert second == first
    stage = store.stages(store.order(order_no).id)[0]
    assert stage.status == "waiting"
    assert [j["media_id"] for j in store.stage_jobs(stage.id)] == [first, first]


def test_finish_stage_carries_its_own_values(setup):
    """BUG-090: die Fertigstellen-Stufe trägt eigene Werte am Auftrag – hier ein Video aus dem
    gewählten Bild mit Pflicht-Prompt und Länge; ohne Prompt klare Ablehnung."""
    from darkfluenzer.nodes import comfy

    cfg, store, man = setup
    with pytest.raises(pipeline.PipelineError, match="braucht zusätzlich"):
        orders.create_order(
            store, man, "lustify_sdxl_t2i", {"prompt": "p", "seed": 1}, {}, count=2,
            finish_workflow="ltx25_i2v", command=_command("ohne"),
        )  # fmt: skip
    with pytest.raises(comfy.ComfyError):
        orders.create_order(
            store, man, "lustify_sdxl_t2i", {"prompt": "p", "seed": 1}, {}, count=2,
            finish_workflow="ltx25_i2v", finish_values={"prompt": "dreht sich", "fps": 25},
            command=_command("falsch"),
        )  # fmt: skip
    order_no, jobs = orders.create_order(
        store, man, "lustify_sdxl_t2i", {"prompt": "p", "seed": 1}, {}, count=2,
        finish_workflow="ltx25_i2v", finish_values={"prompt": "dreht sich", "duration_s": 3},
        command=_command("mit"),
    )  # fmt: skip
    picked = _finish(cfg, store, jobs[0])
    _finish(cfg, store, jobs[1])
    (finish_job,) = orders.select_candidate(cfg, store, man, order_no, picked, _command("wahl"))
    params = store.job(finish_job)["params"]
    assert params["prompt"] == "dreht sich" and params["video"]["length"] == 3
    assert params["image"].endswith(".png")


def test_content_tier_from_every_input_file(setup):
    """SP2 Schritt 2 (BUG-047): Upload, Vorlage oder Medien-ID ohne Eltern – die Stufe der
    Eingabedatei zählt (Galerie-Treffer über SHA-256, sonst explizit); „Wiederholen“ erbt."""
    cfg, store, man = setup

    def gallery(name: str, color: int, tier: str) -> int:
        rel = f"evaluation/t/{name}.png"
        (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), (color, 0, 0)).save(cfg.local / rel)
        data = (cfg.local / rel).read_bytes()
        mid = store.add_media(rel, hashlib.sha256(data).hexdigest(), len(data))
        store.db.execute("UPDATE media SET content_tier = ? WHERE id = ?", (tier, mid))
        return mid

    def render(image_rel: str, **kw) -> str:
        job = pipeline.create_render(
            store, man, "ltx25_i2v", {"prompt": "p"}, {"image": image_rel}, video_max_s=120, **kw
        )
        return store.job(job)["content_tier"]

    standard = gallery("standard", 10, "standard")
    explicit = gallery("explizit", 200, "explizit")
    # Medien-ID ohne Eltern: Kopie in inputs/ mit denselben Bytes
    assert render(pipeline.input_from_media(cfg, standard)) == "standard"
    assert render(pipeline.input_from_media(cfg, explicit)) == "explizit"
    # fremder Upload (nicht in der Galerie) -> explizit
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (0, 99, 0)).save(buf, "PNG")
    foreign = pipeline.store_input(cfg, buf.getvalue(), "fremd.png")
    assert render(foreign) == "explizit"
    # „Wiederholen“ erbt die Stufe des Ursprungsjobs, auch mit unverdächtiger Eingabe
    assert render(pipeline.input_from_media(cfg, standard), inherit_tier="explizit") == "explizit"


def test_queue_priority_classes_and_order(setup):
    """SP5 Schritt 5 (BUG-101): Klasse aus der Auftragsquelle, Auswahl nach Vorrang (Konfiguration),
    je Klasse FIFO; ein Training kommt zuletzt."""
    cfg, store, man = setup
    _, cockpit_jobs = orders.create_order(
        store, man, "lustify_sdxl_t2i", {"prompt": "p", "seed": 1}, {}, count=1,
        command=_command("cockpit"),
    )  # fmt: skip
    _, cloner_jobs = orders.create_order(
        store, man, "lustify_sdxl_t2i", {"prompt": "p", "seed": 1}, {}, count=1,
        command=_command("kloner"), source="cloner",
    )  # fmt: skip
    training = store.create_job(None, "e", "wf_train", "p", {}, [], priority="training")
    customer = store.create_job(None, "e", "wf", "p", {}, [], priority="customer")
    assert store.job_priorities([cockpit_jobs[0], cloner_jobs[0]]) == {
        cockpit_jobs[0]: "cockpit",
        cloner_jobs[0]: "default",
    }
    order = cfg.production.priority
    assert [j for j, _ in store.queued_jobs(order)] == [
        customer,
        cloner_jobs[0],
        cockpit_jobs[0],
        training,
    ]
    # Reihenfolge kommt aus der Konfiguration: andere Reihenfolge, andere Auswahl
    flipped = ("training", "cockpit", "default", "customer")
    assert [j for j, _ in store.queued_jobs(flipped)][0] == training
    assert [j for j, _ in store.queued_jobs()][0] == cockpit_jobs[0]  # ohne Vorrang: FIFO


def test_sizes_native_and_upscaled_are_kept_apart(setup):
    """SP3 Ausgabe: Abmessungen aus dem Dateikopf; nach Hochskalieren oder Ausgabeformat ist
    nativ die Größe des Ausgangsmediums, nie die Ausgabegröße; vorhandene Bilder werden
    nachgetragen."""
    from darkfluenzer.media import gallery

    cfg, store, man = setup

    def png(name: str, w: int, h: int) -> dict:
        rel = f"evaluation/test/{name}.png"
        (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (w, h), (w % 255, h % 255, 7)).save(cfg.local / rel)
        data = (cfg.local / rel).read_bytes()
        return {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}

    master_job = store.create_job(None, "e", "lustify_sdxl_t2i", "p", {}, [])
    master = pipeline.register_outputs(store, master_job, [png("m", 96, 64)], local=cfg.local)
    row = store.media_by_id(master)
    assert (row["width"], row["height"], row["native_width"], row["native_height"]) == (
        96,
        64,
        96,
        64,
    )
    up_job = store.create_job(None, "e", "seedvr2_upscale_image", "p", {}, [])
    up = pipeline.register_outputs(
        store, up_job, [png("u", 192, 128)], local=cfg.local, resized=True, parent=master
    )
    row = store.media_by_id(up)
    assert (row["width"], row["height"], row["native_width"], row["native_height"]) == (
        192,
        128,
        96,
        64,
    )
    lost = pipeline.register_outputs(
        store, up_job, [png("x", 300, 200)], local=cfg.local, resized=True, parent=None
    )
    assert store.media_by_id(lost)["native_width"] is None  # unbekannt, nie die Ausgabegröße
    # Nachtrag: ein Bild ohne Abmessungen (z. B. aus dem Ordner-Scan)
    old_job = store.create_job(
        None, "e", "seedvr2_upscale_image", "p", {}, [], parent_media_id=master
    )
    out = png("o", 120, 80)
    old = store.add_media(out["path"], out["sha256"], out["size"], job_id=old_job)
    assert store.media_by_id(old)["width"] is None
    assert gallery.fill_sizes(cfg, store, frozenset({"seedvr2_upscale_image"}), 10) == 1
    row = store.media_by_id(old)
    assert (row["width"], row["height"], row["native_width"], row["native_height"]) == (
        120,
        80,
        96,
        64,
    )


def test_keyframes_count_for_the_content_tier(setup):
    """FABLE-008 (P0, Audit 17.11.): jedes weitere Schlüsselbild zählt für die Inhaltsstufe wie ein
    Upload – Galerie-Treffer über SHA-256 mit dessen Stufe, fremdes Bild explizit; die höchste Stufe
    aller Eingaben gilt, auch beim Wiederholen."""
    cfg, store, man = setup

    def gallery(name: str, color: int, tier: str) -> str:
        rel = f"evaluation/t/{name}.png"
        (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), (color, 7, 0)).save(cfg.local / rel)
        data = (cfg.local / rel).read_bytes()
        mid = store.add_media(rel, hashlib.sha256(data).hexdigest(), len(data))
        store.db.execute("UPDATE media SET content_tier = ? WHERE id = ?", (tier, mid))
        return pipeline.input_from_media(cfg, mid)

    standard, standard2 = gallery("s1", 10, "standard"), gallery("s2", 20, "standard")
    explicit = gallery("x", 200, "explizit")
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (0, 99, 7)).save(buf, "PNG")
    foreign = pipeline.store_input(cfg, buf.getvalue(), "fremd.png")

    def render(*frames: str) -> int:
        return pipeline.create_render(
            store, man, "ltx25_flf2v", {"prompt": "p", "duration_s": 2.0},
            {"image": standard, "end_image": standard2}, video_max_s=120, keyframes_max=4,
            keyframes=[{"at_s": 0.5 + i * 0.5, "image": f} for i, f in enumerate(frames)],
        )  # fmt: skip

    assert man.workflows["ltx25_flf2v"].content == "standard"
    tier = lambda job: store.job(job)["content_tier"]  # noqa: E731
    assert tier(render()) == "standard"
    assert tier(render(standard)) == "standard"  # Galerie-Medium der Stufe standard
    assert tier(render(explicit)) == "explizit"  # Galerie-Medium explizit
    assert tier(render(foreign)) == "explizit"  # fremdes Bild: unbekannt gilt als explizit
    mixed = render(standard, explicit)
    assert tier(mixed) == "explizit"  # gemischt: die höchste Stufe
    order_no, (job,) = orders.create_order(
        store, man, "ltx25_flf2v", {"prompt": "p", "duration_s": 2.0},
        {"image": standard, "end_image": standard2}, count=1, video_max_s=120, keyframes_max=4,
        keyframes=[{"at_s": 1.0, "image": explicit}],
    )  # fmt: skip
    assert tier(job) == "explizit"
    _finish(cfg, store, job, ok=False)
    (again,) = orders.retry_stage(store, man, order_no, 1, 3, _command("retry-kf"), video_max_s=120)
    assert tier(again) == "explizit" and store.job(again)["params"]["keyframes"]


def test_retry_of_a_seconds_video_keeps_its_length(setup):
    """BUG-109: Wiederholen eines Sekunden-Videos (LTX) übernimmt duration_s und das gespeicherte
    segment_s = 0; vorher scheiterte es an „Abschnitte gibt es bei diesem Workflow nicht“. Ein
    echter Abschnittswert bleibt abgelehnt."""
    cfg, store, man = setup
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (5, 5, 5)).save(buf, "PNG")
    image = pipeline.store_input(cfg, buf.getvalue(), "start.png")
    order_no, (job,) = orders.create_order(
        store, man, "ltx25_i2v", {"prompt": "p", "duration_s": 3.0}, {"image": image}, count=1,
        video_max_s=120,
    )  # fmt: skip
    assert store.job(job)["params"]["segment_s"] == 0.0
    _finish(cfg, store, job, ok=False)
    (again,) = orders.retry_stage(
        store, man, order_no, 1, 3, _command("retry-ltx"), video_max_s=120
    )
    assert store.job(again)["params"]["duration_s"] == 3.0
    with pytest.raises(pipeline.PipelineError, match="Abschnitte"):
        pipeline.create_render(store, man, "ltx25_i2v", {"prompt": "p", "segment_s": 2.0},
                               {"image": image}, video_max_s=120)  # fmt: skip
