# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import asyncio
import copy
import inspect
import sys
import time
from collections.abc import Mapping
from typing import Any, cast

import cli_ui

from src import webui_events
from src.cleanup import cleanup_manager
from src.console import logger, prompt_in_thread
from src.dupe_checking import DupeChecker
from src.imdb import imdb_manager
from src.languages import languages_manager
from src.meta import Meta
from src.metadata_searching import get_douban_id
from src.runtime.tracker_requests import retry_readonly
from src.slot_rules.models import Verdict
from src.slot_rules.registry import evaluate_slots
from src.stats import record_event_async
from src.trackers.AVISTAZ.routing import AvistaZNetworkRouter
from src.trackers.GAZELLE.passthepopcorn import PassThePopcorn
from src.trackersetup import TrackerSetup, tracker_class_map
from src.uphelper import UploadHelper


def merge_tracker_status(processed: dict[str, dict[str, Any]], existing: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Preserve routing metadata while keeping fresh processing results authoritative."""
    merged = {tracker: dict(status) for tracker, status in existing.items()}
    for tracker, status in processed.items():
        merged.setdefault(tracker, {}).update(status)
    return merged


def requires_english_subtitles_for_non_english_audio(meta: Meta, tracker: str) -> bool:
    """Apply the user's baseline subtitle rule before tracker-specific checks."""
    if tracker.upper() == "DESITORRENTS" or meta.category not in {"MOVIE", "TV"}:
        return False

    def has_english(languages: Any) -> bool:
        values = [languages] if isinstance(languages, str) else languages or []
        return any(
            (normalized := str(language).strip().lower()) in {"en", "eng", "english", "en-us", "en-gb"}
            or normalized.startswith("english ")
            or normalized.startswith("english(")
            for language in values
        )

    audio_languages = meta.audio_languages or []
    return bool(audio_languages) and not has_english(audio_languages) and not has_english(meta.subtitle_languages or [])


class TrackerStatusManager:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.trackers_config = cast(Mapping[str, Mapping[str, Any]], config.get("TRACKERS", {}))

    async def _run_additional_checks(self, tracker_name: str, tracker: Any, meta: Meta, helper: Any) -> bool:
        """Run tracker checks and let an attended user override a failed check.

        Tracker checks deliberately remain responsible for validating tracker rules
        and explaining failures.  The upload decision belongs here so every
        tracker gets the same attended/unattended behaviour.
        """
        check = getattr(tracker, "get_additional_checks", None)
        if check is None:
            return True

        with webui_events.capture_tracker_checks(tracker_name, logger) as messages:
            result = await check(meta) if inspect.iscoroutinefunction(check) else check(meta)
        if result:
            return True

        if not meta.get("unattended", False) and not sys.stdin.closed:
            try:
                with webui_events.prompt_context(
                    tracker=tracker_name,
                    check_messages=messages or ["The tracker did not report a specific reason for this failed check."],
                ):
                    if await helper.prompt_yes_no(
                        f"{tracker_name}: one or more upload checks failed. Do you want to proceed with the upload anyway?",
                        default=False,
                    ):
                        return True
            except EOFError:
                pass

        status = meta.tracker_status.setdefault(tracker_name, {})
        status["status_message"] = "\n".join(messages) or status.get("status_message") or "Upload checks failed"
        return False

    async def process_all_trackers(self, meta: Meta) -> int:
        """Check selected trackers and retain their decisions and explanations in shared metadata."""
        tracker_status: dict[str, dict[str, Any]] = {}
        successful_trackers = 0
        tracker_setup: Any = TrackerSetup(config=self.config)
        tracker_setup.filter_unsupported_trackers(meta)
        await AvistaZNetworkRouter(self.config, tracker_class_map).apply(meta)
        helper: Any = UploadHelper(self.config)
        dupe_checker = DupeChecker(self.config)
        meta_lock = asyncio.Lock()
        status_map = meta.tracker_status
        for tracker in meta.trackers:
            if tracker not in status_map:
                status_map[tracker] = {}

        # Prompt for IMDB ID once if any tracker needs it and it's missing in attended mode
        if not meta.get("unattended", False) and not meta.get("no_imdb", False) and meta.get("imdb_id", 0) == 0:
            needs_imdb = "PASSTHEPOPCORN" in meta.trackers
            if needs_imdb:
                while True:
                    try:
                        with webui_events.answer_buttons([("", "Skip trackers that need it")]):
                            imdb_id = await prompt_in_thread(
                                cli_ui.ask_string, "Unable to find IMDB id, please enter e.g.(tt1234567) or press Enter to skip uploading to trackers requiring it:"
                            )
                    except EOFError:
                        logger.info("\n[red]Exiting on user request (Ctrl+C)[/red]")
                        await cleanup_manager.cleanup()
                        cleanup_manager.reset_terminal()
                        sys.exit(1)

                    if imdb_id is None or imdb_id.strip() == "":
                        meta["imdb_id"] = 0
                        break

                    imdb_id = imdb_id.strip().lower()
                    if imdb_id.startswith("tt") and imdb_id[2:].isdigit():
                        meta["imdb_id"] = int(imdb_id[2:])
                        meta["imdb"] = imdb_id[2:].zfill(7)
                        meta["imdb_tt"] = imdb_id
                        meta["imdb_info"] = await imdb_manager.get_imdb_info_api(
                            meta["imdb_id"],
                            manual_language=meta.get("manual_language"),
                        )
                        break
                    cli_ui.error("Invalid IMDB ID format. Expected format: tt1234567")

        if any(
            tracker in meta.trackers
            for tracker in [
                "1PTBA",
                "LAJIDUI",
                "LEMONHD",
                "LONGPT",
                "MTEAM",
                "PTCAFE",
                "PTERCLUB",
                "PTFANS",
                "PTGTK",
                "PTZONE",
                "QINGWA",
                "RAILGUNPT",
                "XINGYUNGEPT",
            ]
        ):
            meta.douban_id = await get_douban_id(meta)

        async def process_single_tracker(tracker_name: str, shared_meta: Meta) -> tuple[str, dict[str, Any], str | None, Any]:
            """Check one isolated metadata copy and return its authoritative tracker result."""
            local_meta = copy.deepcopy(shared_meta)  # Ensure each task gets its own copy of meta
            # ``skipping`` is legacy tracker-local state.  A failed tracker can
            # leave it populated on the shared metadata, which must not prevent
            # other trackers from running their duplicate checks.
            local_meta.skipping = None
            local_tracker_status: dict[str, Any] = {"banned": False, "skipped": False, "dupe": False, "upload": False, "other": False, "skip_reason": ""}
            display_name = None
            tracker_class = None

            if local_meta["name"].endswith("DUPE?"):
                local_meta["name"] = local_meta["name"].replace(" DUPE?", "")

            if local_meta.hdb_manual and tracker_name == "HDBITS":
                local_tracker_status.update(manual_pending=True, manual_prepared=False, upload_success=None)
                return tracker_name, local_tracker_status, None, None

            if tracker_name in ("MANUAL", "USENET"):
                local_tracker_status["upload"] = True
                return tracker_name, local_tracker_status, None, None

            if tracker_name in tracker_class_map:
                tracker_class = tracker_class_map[tracker_name](config=self.config)
                if tracker_name == "PASSTHEPOPCORN" and local_meta.get("imdb_id", 0) == 0:
                    local_tracker_status["skipped"] = True
                    local_tracker_status["skip_reason"] = "missing IMDb ID"

                if not local_tracker_status["skipped"]:
                    result = await tracker_setup.check_banned_group(tracker_class.tracker, tracker_class.banned_groups, local_meta)
                    local_tracker_status["banned"] = bool(result)

                if local_meta["tracker_status"][tracker_name].get("skip_upload") and not meta.force_upload:
                    local_tracker_status["skipped"] = True
                    local_tracker_status["skip_reason"] = "tracker status marked upload as skipped"
                elif "skipped" not in local_meta and not local_tracker_status["skipped"]:
                    local_tracker_status["skipped"] = False

                # Check for missing required BOOK fields in unattended mode
                if local_meta.get("category") == "BOOK" and local_meta.get("unattended", False):
                    from src.book_prep import is_valid_book_language

                    book_required_fields = ["title", "author", "year", "book_language"]
                    book_missing: list[str] = []
                    for f in book_required_fields:
                        val = local_meta.get(f)
                        if not val or str(val).strip().lower() in ("", "none", "null"):
                            book_missing.append(f)
                        elif f == "book_language":
                            iso = local_meta.get("book_language_iso", "")
                            if not is_valid_book_language(str(val), str(iso)):
                                book_missing.append(f)
                    if book_missing:
                        logger.info(f"[yellow]{tracker_name}: Skipping upload because required BOOK fields are missing: {', '.join(book_missing)}[/yellow]")
                        local_tracker_status["skipped"] = True
                        local_tracker_status["skip_reason"] = f"missing required BOOK fields: {', '.join(book_missing)}"

                # Check for missing required GAME fields in unattended mode
                elif local_meta.get("category") == "GAME" and local_meta.get("unattended", False):
                    game_required_fields = ["title", "year", "platform"]
                    game_missing: list[str] = []
                    for f in game_required_fields:
                        val = local_meta.get(f)
                        if not val or str(val).strip().lower() in ("", "none", "null") or (f == "platform" and "," in str(val)):
                            game_missing.append(f)
                    if game_missing:
                        logger.info(f"[yellow]{tracker_name}: Skipping upload because required GAME fields are missing: {', '.join(game_missing)}[/yellow]")
                        local_tracker_status["skipped"] = True
                        local_tracker_status["skip_reason"] = f"missing required GAME fields: {', '.join(game_missing)}"

                if not local_tracker_status["banned"] and not local_tracker_status["skipped"]:
                    if not local_meta.language_checked:
                        await languages_manager.process_desc_language(local_meta, tracker=tracker_name)
                    if requires_english_subtitles_for_non_english_audio(local_meta, tracker_name):
                        logger.info(f"[yellow]{tracker_name}: Skipping upload because non-English audio requires English subtitles.[/yellow]")
                        local_tracker_status["skipped"] = True
                        local_tracker_status["skip_reason"] = "non-English audio requires English subtitles"

                if not local_tracker_status["banned"] and not local_tracker_status["skipped"]:
                    claimed = await tracker_setup.get_torrent_claims(local_meta, tracker_name)
                    local_tracker_status["skipped"] = bool(claimed)
                    if claimed:
                        local_tracker_status["status_message"] = local_meta.tracker_status[tracker_name].get("status_message") or "Claimed release found on this tracker"
                        local_tracker_status["skip_reason"] = local_tracker_status["status_message"]

                    if tracker_name not in {"PASSTHEPOPCORN"} and not local_tracker_status["skipped"]:
                        should_continue = await self._run_additional_checks(tracker_name, tracker_class, local_meta, helper)
                        if not should_continue:
                            local_tracker_status["skipped"] = True
                            local_tracker_status["status_message"] = local_meta.tracker_status[tracker_name].get("status_message") or "Upload checks failed"
                            local_meta.skipping = tracker_name
                            local_tracker_status["skip_reason"] = "tracker-specific media requirements failed"

                        if not local_tracker_status["skipped"]:
                            search_started = time.monotonic()
                            try:
                                local_meta[f'{tracker_name}_search_failed'] = False
                                dupes: list[Any] = cast(list[Any], await retry_readonly(lambda: tracker_class.search_existing(local_meta), tracker_name))
                                await record_event_async(
                                    "api", service=tracker_name, operation="search", outcome="success", duration_ms=(time.monotonic() - search_started) * 1000
                                )
                                # set trackers here so that they are not double checked later with cross seeding
                                async with meta_lock:
                                    meta.setdefault("dupe_checked_trackers", []).append(tracker_name)
                                if local_meta["tracker_status"][tracker_name].get("other", False):
                                    local_tracker_status["other"] = True
                            except Exception as e:
                                local_meta[f'{tracker_name}_search_failed'] = True
                                await record_event_async(
                                    "api", service=tracker_name, operation="search", outcome="error", duration_ms=(time.monotonic() - search_started) * 1000
                                )
                                logger.info(f"[bold red]Error searching for duplicates on {tracker_name}: {e}[/bold red]")
                                if local_meta.get("unattended", False):
                                    local_tracker_status["skipped"] = True
                                    local_meta.skipping = tracker_name
                                    local_tracker_status["skip_reason"] = f"duplicate search failed: {e}"
                                    dupes = []
                                else:
                                    try:
                                        if await helper.prompt_yes_no(
                                            f"Duplicate check failed on {tracker_name}. Do you want to proceed with the upload anyway?", default=False
                                        ):
                                            dupes = []
                                            # set trackers here so that they are not double checked later with cross seeding
                                            async with meta_lock:
                                                meta.setdefault("dupe_checked_trackers", []).append(tracker_name)
                                        else:
                                            local_tracker_status["skipped"] = True
                                            local_meta.skipping = tracker_name
                                            local_tracker_status["skip_reason"] = "duplicate search was declined"
                                            dupes = []
                                    except EOFError:
                                        logger.info("\n[red]Exiting on user request (Ctrl+C)[/red]")
                                        await cleanup_manager.cleanup()
                                        cleanup_manager.reset_terminal()
                                        sys.exit(1)
                        else:
                            dupes = []
                    elif tracker_name == "PASSTHEPOPCORN":
                        ptp: Any = PassThePopcorn(config=self.config)
                        should_continue = await self._run_additional_checks(tracker_name, ptp, local_meta, helper)
                        if not should_continue:
                            local_tracker_status["skipped"] = True
                            local_tracker_status["status_message"] = local_meta.tracker_status[tracker_name].get("status_message") or "Upload checks failed"
                            local_meta.skipping = tracker_name
                            local_tracker_status["skip_reason"] = "tracker-specific media requirements failed"

                        if not local_tracker_status["skipped"]:
                            search_started = time.monotonic()
                            try:
                                group_id = await retry_readonly(lambda: ptp.get_group_by_imdb(local_meta['imdb'], strict=True, allow_prompt=not local_meta.unattended or bool(local_meta.unattended_confirm)), tracker_name, operation_name='PTP group lookup')
                                async with meta_lock:
                                    meta.ptp_groupid = group_id
                                dupes = cast(list[Any], await retry_readonly(lambda: ptp.search_existing(group_id or '', local_meta), tracker_name))
                                await record_event_async(
                                    "api", service=tracker_name, operation="search", outcome="success", duration_ms=(time.monotonic() - search_started) * 1000
                                )
                            except Exception:
                                await record_event_async(
                                    "api", service=tracker_name, operation="search", outcome="error", duration_ms=(time.monotonic() - search_started) * 1000
                                )
                                logger.warning("PASSTHEPOPCORN: group search failed; slot occupancy is unknown. Skipping PTP, not the other trackers.")
                                local_tracker_status["skipped"] = True
                                local_meta.skipping = tracker_name
                                local_tracker_status["skip_reason"] = "PTP group search failed; slot occupancy is unknown"
                                dupes = []
                        else:
                            dupes = []
                    else:
                        dupes = []

                    async with meta_lock:
                        if "initial_dupes" not in meta:
                            meta.initial_dupes = {}
                        meta.initial_dupes[tracker_name] = copy.deepcopy(dupes)

                    if tracker_name == "AMIGOSSHARE" and (meta.anon if meta.anon is not None else "false"):
                        logger.info(
                            "PORTUGAS: [yellow]Aviso: Você solicitou um upload anônimo, mas o AMIGOSSHARE não suporta essa opção.[/yellow][red] O envio não será anônimo.[/red]"
                        )
                        logger.warning(
                            "EN: [yellow]Warning: You requested an anonymous upload, but AMIGOSSHARE does not support this option.[/yellow][red] The upload will not be anonymous.[/red]"
                        )

                    # The per-tracker status is authoritative here. Do not
                    # consult the legacy ``meta.skipping`` marker, which may
                    # have been set by a different tracker.
                    if not local_tracker_status["skipped"]:
                        # Keep the title search targets available for explicit manual
                        # reports even if the basic duplicate filter removes them.
                        if tracker_name in {"AITHER", "LST"}:
                            local_meta[f"{tracker_name}_report_candidates"] = [dict(entry) for entry in dupes if isinstance(entry, dict)]
                        # Slot rules need the unfiltered results; the basic filter drops releases they compare against.
                        slot_decision = await evaluate_slots(dupes, local_meta, tracker_name, self.config)
                        dupes = cast(list[Any], await dupe_checker.filter_dupes(dupes, local_meta, tracker_name))

                        # Run dupe check first so it can modify local_meta (e.g., set cross-seed values)
                        is_dupe, local_meta = await helper.dupe_check(dupes, local_meta, tracker_name, slot_decision)
                        if is_dupe:
                            if slot_decision is not None:
                                explanation = slot_decision.reason
                                if slot_decision.why and slot_decision.why != explanation:
                                    explanation += " Why: " + slot_decision.why
                                local_tracker_status["skip_reason"] = explanation
                                local_tracker_status["status_message"] = f"{tracker_name} slot check: {explanation}"
                            policy_rejection = slot_decision is not None and (
                                (tracker_name == "PASSTHEPOPCORN" and slot_decision.verdict in {Verdict.BLOCK, Verdict.REVIEW}) or
                                (tracker_name in {"AITHER", "HDBITS", "LST", "BLUTOPIA"} and (slot_decision.verdict is Verdict.BLOCK or
                                                               (slot_decision.verdict is Verdict.REVIEW and slot_decision.requires_evidence))))
                            if policy_rejection and slot_decision is not None:
                                local_tracker_status["skipped"] = True
                                local_tracker_status["status_message"] = f"{tracker_name} policy check: " + str(local_tracker_status["skip_reason"])
                            else:
                                local_tracker_status["dupe"] = True

                        matched_episode_ids = local_meta.get(f"{tracker_name}_matched_episode_ids", [])
                        trumpable_id = local_meta.get("trumpable_id")
                        cross_seed_key = f"{tracker_name}_cross_seed"
                        cross_seed_value = local_meta.get(cross_seed_key) if cross_seed_key in local_meta else None

                        # Only shared-state writes go under the lock
                        async with meta_lock:
                            if matched_episode_ids:
                                meta[f"{tracker_name}_matched_episode_ids"] = matched_episode_ids
                            if trumpable_id:
                                meta.trumpable_id = trumpable_id
                            if cross_seed_key in local_meta:
                                meta[cross_seed_key] = cross_seed_value

                        if tracker_name in ["AITHER", "LST"]:
                            were_trumping = local_meta.get("were_trumping", False)
                            trump_reason = local_meta.get("trump_reason")
                            trumpable_id_after_dupe_check = local_meta.get(f"{tracker_name}_trumpable_id")
                            async with meta_lock:
                                meta[f"{tracker_name}_were_trumping"] = bool(were_trumping)
                                if tracker_name == "LST":
                                    meta["LST_protected_ids"] = local_meta.get("LST_protected_ids", [])
                                if were_trumping:
                                    meta.were_trumping = were_trumping
                                if trump_reason:
                                    meta.trump_reason = trump_reason
                                    meta[f"{tracker_name}_trump_reason"] = trump_reason
                                if trumpable_id_after_dupe_check:
                                    meta[f"{tracker_name}_trumpable_id"] = trumpable_id_after_dupe_check

                # Determine name change for display during interactive prompt
                if not local_tracker_status["banned"] and not local_tracker_status["skipped"] and not local_tracker_status["dupe"]:
                    try:
                        tracker_rename = await tracker_class.get_name(local_meta)
                    except Exception:
                        tracker_rename = None

                    if tracker_rename is not None:
                        if isinstance(tracker_rename, dict) and "name" in tracker_rename:
                            display_name = cast(str, tracker_rename["name"])
                        elif isinstance(tracker_rename, str):
                            display_name = tracker_rename

            return tracker_name, local_tracker_status, display_name, tracker_class

        searching_trackers: list[str] = [name for name in meta.trackers if name in tracker_class_map]
        if searching_trackers:
            logger.info("[yellow]Searching for existing torrents on selected trackers...")

        async def check_tracker(tracker_name: str) -> tuple[str, dict[str, Any], str | None, Any]:
            """Finish discovery even when a tracker exits before duplicate review."""
            try:
                return await process_single_tracker(tracker_name, meta)
            finally:
                webui_events.dupe_review_ready(tracker_name, finished=True)

        with webui_events.dupe_review_scope(meta.trackers):
            results = await asyncio.gather(*(check_tracker(tracker_name) for tracker_name in meta.trackers))

        # Collect passed trackers and skip reasons
        passed_trackers: list[tuple[str, str | None, Any]] = []
        dupe_trackers: list[str] = []
        skipped_trackers: list[str] = []

        for tracker_name, status, display_name, tracker_class in results:
            tracker_status[tracker_name] = status
            if status.get("manual_pending"):
                logger.info("HDBITS: local manual preparation only; no authentication or duplicate check performed.")
                continue
            if status["banned"]:
                pass
            elif status["skipped"]:
                skipped_trackers.append(tracker_name)
                reason = str(status.get("skip_reason") or "unspecified tracker condition")
                logger.info(f"[yellow]{tracker_name}: skipped before upload ({reason})[/yellow]")
            elif status["dupe"]:
                dupe_trackers.append(tracker_name)
            else:
                passed_trackers.append((tracker_name, display_name, tracker_class))

        if skipped_trackers:
            logger.info(f"[red]Skipped due to specific tracker conditions: [bold yellow]{', '.join(skipped_trackers)}[/bold yellow].", extra={"ua_gui": False})
        if dupe_trackers:
            logger.info(f"[red]Found potential dupes on: [bold yellow]{', '.join(dupe_trackers)}[/bold yellow].\n", extra={"ua_gui": False})

        # Now handle the confirmation/upload decisions
        if meta.unattended:
            passed_names: list[str] = []
            for tracker_name, _display_name, _tracker_class in passed_trackers:
                tracker_status[tracker_name]["upload"] = True
                successful_trackers += 1
                passed_names.append(tracker_name)
            if passed_names:
                logger.info(f"[bold]{', '.join(passed_names)}[/bold]: [bold green]no potential dupes found.[/bold green]")
        else:
            # Attended mode
            prompt_trackers = [tracker_name for tracker_name, _display_name, _tracker_class in passed_trackers if tracker_name not in ("MANUAL", "USENET")]

            if not meta.get("debug", False) and prompt_trackers:
                if len(prompt_trackers) == 1:
                    tracker_name = prompt_trackers[0]
                    logger.info(f"[bold]{tracker_name}:[/bold] [green]no potential dupes found.[/green]")
                    prompt_msg = "Upload?"
                else:
                    logger.info(f"[bold]{', '.join(prompt_trackers)}:[/bold] [green]no potential dupes found.[/green]")
                    prompt_msg = "Upload to all?"

                try:
                    with webui_events.prompt_context(
                        kind="dupe_clear",
                        clear_trackers=",".join(prompt_trackers),
                        dupe_trackers=",".join(dupe_trackers),
                        skipped_trackers=",".join(skipped_trackers),
                    ):
                        upload_all = await helper.prompt_yes_no(prompt_msg, default=False)
                except EOFError:
                    logger.info("\n[red]Exiting on user request (Ctrl+C)[/red]")
                    await cleanup_manager.cleanup()
                    cleanup_manager.reset_terminal()
                    sys.exit(1)

                if upload_all:
                    logger.info("[yellow]Processing approved uploads in the background...[/yellow]")

                for tracker_name, _display_name, _tracker_class in passed_trackers:
                    if tracker_name in ("MANUAL", "USENET"):
                        tracker_status[tracker_name]["upload"] = True
                        successful_trackers += 1
                    else:
                        if upload_all:
                            tracker_status[tracker_name]["upload"] = True
                            successful_trackers += 1
                        else:
                            tracker_status[tracker_name]["upload"] = False
            else:
                # No prompt required (either empty passed_trackers/prompt_trackers, or in debug mode)
                for tracker_name, _display_name, _tracker_class in passed_trackers:
                    tracker_status[tracker_name]["upload"] = True
                    successful_trackers += 1

        if meta.debug:
            logger.debug("\n[bold]Tracker Processing Summary:[/bold]")
            for t_name, status in tracker_status.items():
                banned_status = "Yes" if status["banned"] else "No"
                skipped_status = "Yes" if status["skipped"] else "No"
                dupe_status = "Yes" if status["dupe"] else "No"
                upload_status = "Yes" if status["upload"] else "No"
                logger.debug(f"Tracker: {t_name} | Banned: {banned_status} | Skipped: {skipped_status} | Dupe: {dupe_status} | [yellow]Upload:[/yellow] {upload_status}")
            logger.debug(f"\n[bold]Trackers Passed all Checks:[/bold] {successful_trackers}")
            logger.debug("", extra={"markup": False})
            logger.debug("[bold red]DEBUG MODE does not upload to sites")

        meta.tracker_status = merge_tracker_status(tracker_status, status_map)
        webui_events.publish_tracker_statuses(meta.tracker_status)
        return successful_trackers


async def process_all_trackers(meta: Meta, config: dict[str, Any]) -> int:
    return await TrackerStatusManager(config=config).process_all_trackers(meta)
