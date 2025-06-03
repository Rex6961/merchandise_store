import logging
from typing import Optional, Sequence, Any

from aiogram import F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import Scene, on
from asgiref.sync import sync_to_async

from bot.misc.paginator import Paginator, MovePage, PageNode, PageContent, UID_TYPE
from admin_panel.clients.models import FAQEntry

logger = logging.getLogger(__name__)

async def faq_loader_function(
    uid: UID_TYPE, 
    limit: int,
    cursor: int, 
    **kwargs: Any
) -> tuple[Optional[Sequence[PageNode]], bool]:
    """
    Asynchronously loads FAQ entries for pagination, optionally filtering by a search query.

    This function fetches FAQ entries from the database based on the provided limit,
    cursor, and an optional search term passed via kwargs.

    Args:
        uid: The unique identifier for the current paginator level (e.g., "faq_root").
        limit: The maximum number of FAQ entries to fetch for the current page.
        cursor: The starting point (offset) for fetching entries.
        **kwargs: Additional keyword arguments. Expected: "search" (Optional[str]) for filtering.

    Returns:
        A tuple containing:
        - An optional sequence of PageNode objects representing the fetched FAQ entries.
          Returns None if an error occurs or no entries are found.
        - A boolean indicating whether there are more entries to load (True) or not (False).
    """
    search_query: Optional[str] = kwargs.get("search")
    logger.debug(f"faq_loader_function called. UID: {uid}, Limit: {limit}, Cursor: {cursor}, Search Query: '{search_query}'")
    has_more = False

    @sync_to_async
    def _get_faq_entries_from_db(search_term: Optional[str], offset: int, count: int) -> list[FAQEntry]:
        logger.debug(f"DB Query: Fetching FAQ entries. Search: '{search_term}', Offset: {offset}, Count: {count}")
        qs = FAQEntry.objects.all()

        if search_term:
            qs = qs.filter(question__icontains=search_term)
            logger.debug(f"DB Query: Applied search filter for '{search_term}'.")
        
        qs = qs.order_by('question')
        
        result = list(qs[offset : offset + count])
        logger.debug(f"DB Query: Found {len(result)} entries (requested {count}).")
        return result

    try:
        # Fetch one more than limit to check if there are more entries
        db_entries: list[FAQEntry] = await _get_faq_entries_from_db(search_query, cursor, limit + 1)
    except Exception as e:
        logger.error(f"Error fetching FAQ entries from DB: {e}", exc_info=True)
        return None, False

    loaded_nodes: list[PageNode] = []
    if db_entries:
        if len(db_entries) > limit:
            db_entries.pop() # Remove the extra one used for has_more check
            has_more = True
            logger.debug(f"More FAQ entries available beyond this page (has_more=True).")
        
        for entry in db_entries:
            node_uid = f"faq_{entry.id}"
            page_content = PageContent(
                label=entry.question, 
                text=entry.answer,
                kwargs={"question": entry.question}, # Search term will be added by Paginator if active
                is_leaf_node=True
            )
            loaded_nodes.append(PageNode(uid=node_uid, content=page_content))
        logger.info(f"Loaded {len(loaded_nodes)} FAQ PageNodes. Has more: {has_more}.")
            
    return loaded_nodes if loaded_nodes else None, has_more

def faq_formatter(
            text: str,
            **kwargs: Any
    ) -> str:
    """
    Formats the text for an FAQ entry, prepending the question and appending a search term if present.

    Args:
        text: The main text content (answer of the FAQ).
        **kwargs: Additional keyword arguments. Expected:
                  "question" (Optional[str]): The FAQ question.
                  "search" (Optional[str]): The search term used, if any.

    Returns:
        The formatted string for displaying the FAQ entry.
    """
    question = kwargs.get("question")
    search_term = kwargs.get("search") # This 'search' kwarg comes from Paginator's page.content.kwargs
    logger.debug(f"faq_formatter called. Question: '{question}', Search term from kwargs: '{search_term}'")
    
    f_text = ""
    if question:
        f_text = f"Question: {question}\n\n" # "Вопрос: {question}\n\n"
    f_text += text
    if search_term: # If a search was active when this page content was prepared
        f_text += f"\n\nSearch query: {search_term}" # "\n\nПоисковой запрос: {search_term}"
    
    logger.debug(f"Formatted FAQ text preview: '{f_text[:100]}...'")
    return f_text

class FAQ(Scene, state="faq"):
    
    @on.message.enter()
    @on.callback_query.enter()
    async def on_enter(self, event: Message | CallbackQuery, state: FSMContext):
        """
        Handles entry into the FAQ scene.

        Initializes or retrieves the FAQ Paginator instance from FSM context
        and displays the initial FAQ page.

        Args:
            event: The Message or CallbackQuery that triggered scene entry.
            state: The FSMContext for managing state data.
        """
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.info(f"FAQ scene: 'on_enter' triggered by {event_type} for user_id: {user_id}.")

        if isinstance(event, CallbackQuery): # Critical: Answer callback query if it's an entry point
            await event.answer()
            logger.debug(f"FAQ.on_enter: Answered callback query {event.id} for user_id: {user_id}.")

        FAQPaginator: Optional[Paginator] = await state.get_value("faq_paginator_inst", None)
        search_term_from_state = await state.get_value("search_term", None) # Get current search term
        
        if FAQPaginator is None:
            logger.info(f"User {user_id}: No existing FAQ Paginator found in state. Initializing new one.")
            root_faq = PageNode(
                uid="faq_root",
                content=PageContent(text="You are in FAQ:", label="FAQ Root") # "Вы в FAQ:"
            )
            FAQPaginator = Paginator(
                page=root_faq,
                loader_func=faq_loader_function,
                formatter=faq_formatter,
                global_kbd={"To Main Menu": "goto_main_menu"} # "В главное меню"
            )
            logger.debug(f"User {user_id}: New FAQ Paginator initialized with root UID 'faq_root'.")
        else:
            logger.info(f"User {user_id}: Existing FAQ Paginator found in state.")

        # If there's an active search term from state, ensure it's in the paginator's current page kwargs
        # This is important if re-entering the scene with an active search
        if search_term_from_state:
            FAQPaginator.page.content.kwargs["search"] = search_term_from_state
            if "Delete search query" not in FAQPaginator.page.custom_kbd: # "Удалить поисковой запрос"
                 FAQPaginator.page.custom_kbd["Delete search query"] = "delete_search"
            logger.debug(f"User {user_id}: Applied active search term '{search_term_from_state}' from state to Paginator on entry.")
        
        await FAQPaginator.show_page(event=event, search=search_term_from_state) # Pass search term to show_page
        await state.update_data(faq_paginator_inst=FAQPaginator)
        logger.debug(f"User {user_id}: FAQ Paginator instance saved/updated in FSM state.")


    @on.callback_query(MovePage.filter())
    async def handle_navigation(self, callback_query: CallbackQuery, callback_data: MovePage, state: FSMContext):
        """
        Handles navigation callbacks within the FAQ (e.g., next/previous page).

        Retrieves the Paginator instance and current search term from FSM context,
        then delegates navigation handling to the Paginator.

        Args:
            callback_query: The CallbackQuery that triggered navigation.
            callback_data: The MovePage callback data.
            state: The FSMContext for managing state data.
        """
        user_id = callback_query.from_user.id
        logger.info(f"FAQ scene: 'handle_navigation' triggered. User_id: {user_id}, Action: {callback_data.action}, UID: {callback_data.uid}")
        await callback_query.answer() # Critical: Answer callback query
        logger.debug(f"FAQ.handle_navigation: Answered callback query {callback_query.id} for user_id: {user_id}.")

        FAQPaginator: Paginator = await state.get_value("faq_paginator_inst")
        if not FAQPaginator:
            logger.error(f"User {user_id}: FAQ Paginator instance not found in state during navigation. This should not happen. Re-initializing.")
            # Fallback: re-initialize and show root. This is a recovery attempt.
            # Ideally, this situation should be prevented.
            root_faq = PageNode(uid="faq_root", content=PageContent(text="You are in FAQ:", label="FAQ Root"))
            FAQPaginator = Paginator(page=root_faq, loader_func=faq_loader_function, formatter=faq_formatter, global_kbd={"To Main Menu": "goto_main_menu"})
            await FAQPaginator.show_page(event=callback_query) # Show initial page
            await state.update_data(faq_paginator_inst=FAQPaginator)
            return

        search_term = await state.get_value("search_term", None)
        logger.debug(f"User {user_id}: Retrieved search_term '{search_term}' from state for navigation.")
        
        await FAQPaginator.handle_navigation(
            event=callback_query,
            callback_data=callback_data,
            search=search_term # Pass current search term to loader if needed
        )
        await state.update_data(faq_paginator_inst=FAQPaginator) # Save potentially modified Paginator (e.g., new children loaded)
        logger.debug(f"User {user_id}: FAQ Paginator instance updated in FSM state after navigation.")

    @on.message(F.text)
    async def handle_search_query(self, message: Message, state: FSMContext):
        """
        Handles incoming text messages as search queries for the FAQ.

        Updates the Paginator with the new search term, resets its cursor and children,
        and re-displays the page with search results. Stores the search term in FSM context.

        Args:
            message: The Message containing the user's search query.
            state: The FSMContext for managing state data.
        """
        user_id = message.from_user.id
        search_term = message.text
        logger.info(f"FAQ scene: 'handle_search_query' triggered. User_id: {user_id}, Search term: '{search_term}'")

        FAQPaginator: Paginator = await state.get_value("faq_paginator_inst")
        if not FAQPaginator:
            logger.error(f"User {user_id}: FAQ Paginator instance not found in state during search. Re-initializing.")
            # Fallback, similar to navigation
            root_faq = PageNode(uid="faq_root", content=PageContent(text="You are in FAQ:", label="FAQ Root"))
            FAQPaginator = Paginator(page=root_faq, loader_func=faq_loader_function, formatter=faq_formatter, global_kbd={"To Main Menu": "goto_main_menu"})
            # No await state.update_data here yet, will be done after show_page

        # Apply search term to the current root page of the paginator
        FAQPaginator.page.content.kwargs["search"] = search_term
        FAQPaginator.page.custom_kbd["Delete search query"] = "delete_search" # "Удалить поисковой запрос"
        FAQPaginator.cursor = 0 # Reset cursor for new search
        FAQPaginator.page.children = {} # Clear previously loaded children for new search results
        logger.debug(f"User {user_id}: Paginator reset for new search. Cursor=0, Children cleared. Search term '{search_term}' applied to page kwargs and custom_kbd.")

        await FAQPaginator.show_page(
            event=message,
            search=search_term # Pass search term to loader
        )
        await state.update_data(faq_paginator_inst=FAQPaginator)
        await state.update_data(search_term=search_term)
        logger.info(f"User {user_id}: Search results displayed. Paginator and search_term '{search_term}' updated in FSM state.")

    @on.callback_query(F.data == "delete_search")
    async def remove_search_term(self, callback_query: CallbackQuery, state: FSMContext):
        """
        Handles the callback to remove an active search term from the FAQ.

        Removes the search term from the Paginator, resets its cursor and children,
        and re-displays the FAQ page without the search filter. Clears the search
        term from FSM context.

        Args:
            callback_query: The CallbackQuery triggered by "delete_search".
            state: The FSMContext for managing state data.
        """
        user_id = callback_query.from_user.id
        logger.info(f"FAQ scene: 'remove_search_term' triggered by user_id: {user_id}.")
        await callback_query.answer("Search query removed.") # Critical: Answer callback query "Поисковой запрос удален."
        logger.debug(f"FAQ.remove_search_term: Answered callback query {callback_query.id} for user_id: {user_id}.")

        FAQPaginator: Paginator = await state.get_value("faq_paginator_inst")
        if not FAQPaginator:
            logger.error(f"User {user_id}: FAQ Paginator instance not found in state when trying to delete search. Re-initializing.")
            # Fallback
            root_faq = PageNode(uid="faq_root", content=PageContent(text="You are in FAQ:", label="FAQ Root"))
            FAQPaginator = Paginator(page=root_faq, loader_func=faq_loader_function, formatter=faq_formatter, global_kbd={"To Main Menu": "goto_main_menu"})
            # No await state.update_data here yet

        # Remove search term effects from the paginator's current root page
        FAQPaginator.page.content.kwargs.pop("search", None)
        if FAQPaginator.page.custom_kbd and "Delete search query" in FAQPaginator.page.custom_kbd: # "Удалить поисковой запрос"
            del FAQPaginator.page.custom_kbd["Delete search query"]
        FAQPaginator.cursor = 0 # Reset cursor
        FAQPaginator.page.children = {} # Clear children (will be reloaded without search)
        logger.debug(f"User {user_id}: Search term effects removed from Paginator. Cursor=0, Children cleared.")

        await FAQPaginator.show_page(
            event=callback_query # No search term passed, so loader gets None
        )
        await state.update_data(faq_paginator_inst=FAQPaginator)
        await state.update_data(search_term=None) # Clear search term from state
        logger.info(f"User {user_id}: FAQ page reloaded without search. Paginator and search_term (None) updated in FSM state.")

    @on.callback_query.exit()
    @on.message.exit()
    async def exit(self, event: Message | CallbackQuery, state: FSMContext):
        """Действие при выходе из сцены."""
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.debug(f"FAQ scene: 'exit' hook triggered by {event_type} for user_id: {user_id}.")
        pass

    @on.callback_query.leave()
    @on.message.leave()
    async def leave(self, event: Message | CallbackQuery, state: FSMContext):
        """Действие при выходе из сцены."""
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.debug(f"FAQ scene: 'leave' hook triggered by {event_type} for user_id: {user_id}.")
        pass