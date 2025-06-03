from collections.abc import Iterable, Awaitable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypeAlias, Union, Protocol
import uuid
import logging

from aiogram.types import Message, CallbackQuery
from aiogram.filters.callback_data import CallbackData
from aiogram.types.input_file import FSInputFile, BufferedInputFile, URLInputFile
from aiogram.types import InlineKeyboardMarkup

from src.bot.kbd.inline import get_callback_btns
from src.bot.misc.utils import send_or_edit_message

logger = logging.getLogger(__name__)

UID_TYPE: TypeAlias = Union[str, uuid.UUID]
EventType: TypeAlias = Union[Message, CallbackQuery]
KeyboardDataType: TypeAlias = Union[str, CallbackData]
Image: TypeAlias = Union[FSInputFile, BufferedInputFile, URLInputFile]


@dataclass
class PaginatorConfig:
    """
    Configuration settings for the Paginator.

    Attributes:
        obj_count_per_page: The number of items to display per page.
        loading_text: Text to display while content is being loaded.
        error_text: Text to display if an error occurs during loading.
        loader_func: An optional default loader function for this specific node or its children.
    """
    obj_count_per_page: int = 5
    loading_text: str = "Загрузка..."
    error_text: str = "Возникла ошибка. Пожалуйста попробуйте снова."
    loader_func: Optional["LoaderFunctionProtocol"] = None

@dataclass
class PageContent:
    """
    Represents the content of a single page or node in the Paginator.

    Attributes:
        text: The main text content of the page.
        label: An optional short label or title for the page, often used for button text.
        image: An optional image to display with the page content.
        kwargs: A dictionary of additional keyword arguments that can be passed to
                a formatter function or used for other custom logic.
        is_leaf_node: A boolean indicating if this node is a leaf (i.e., has no children
                      and represents a final item rather than a category).
    """
    text: str
    label: Optional[str] = None
    image: Optional[Image] = None
    kwargs: dict[str, Any] = field(default_factory=dict)
    is_leaf_node: bool = False

@dataclass
class PageNode:
    """
    Represents a node in the paginated structure, which can be a page itself or a container for child nodes.

    Attributes:
        uid: A unique identifier for this node (e.g., "catalog_1", "product_1").
        content: The PageContent object holding the displayable information for this node.
        custom_kbd: A dictionary for custom keyboard buttons specific to this node.
                    Keys are button labels (str), values are callback data (str or CallbackData).
        parent: A reference to the parent PageNode, automatically set when added as a child.
        children: A dictionary mapping UIDs to child PageNode objects.
        config: PaginatorConfig settings specific to this node and its children if not overridden.
    """
    uid: UID_TYPE

    content: PageContent

    custom_kbd: dict[str, KeyboardDataType] = field(default_factory=dict)

    parent: Optional["PageNode"] = field(repr=False, init=False, default=None)
    children: dict[UID_TYPE, "PageNode"] = field(default_factory=dict) 

    config: PaginatorConfig = field(default_factory=PaginatorConfig)

    def add_child(self, child_node: "PageNode") -> "PageNode":
        """
        Adds a single child node to this node.

        If a child with the same UID already exists, it will be overwritten.
        Sets the parent of the child_node to self.

        Args:
            child_node: The PageNode to add as a child.

        Returns:
            The current PageNode instance (self) for chaining.
        """
        if child_node.uid in self.children:
            logger.warning(f"Child node with UID '{child_node.uid}' already exists in parent node '{self.uid}' and will be overwritten.") # Changed print to logger.warning and translated
        self.children[child_node.uid] = child_node
        child_node.parent = self
        return self
    
    def add_children(self, children_nodes: Iterable["PageNode"]) -> "PageNode":
        """
        Adds multiple child nodes to this node.

        Args:
            children_nodes: An iterable of PageNode objects to add as children.

        Returns:
            The current PageNode instance (self) for chaining.
        """
        
        count = 0
        for child_node in children_nodes:
            self.add_child(child_node)
            count += 1
        logger.debug(f"Added {count} children to PageNode UID: '{self.uid}'.")
        return self

    def __str__(self) -> str:
            """
            Generates a string representation of the node and its children in a tree-like structure.

            Returns:
                A string depicting the hierarchy of nodes starting from this node.
            """
            result_lines: list[str] = []
            
            stack: list[tuple["PageNode", int]] = []

            stack.append((self, 0)) 

            while stack:
                current_node, level = stack.pop()

                indent = "  " * level
                result_lines.append(f"{indent}- UID: {current_node.uid}, Name: '{current_node.content.label}'")
            
                if current_node.children:
                    children_to_visit = list(current_node.children.values())
                    
                    for child_node in reversed(children_to_visit):
                        stack.append((child_node, level + 1))
                    
            return "\n".join(result_lines)



class LoaderFunctionProtocol(Protocol):
    """
    Protocol for a function that loads child nodes for a given PageNode.

    The function should be asynchronous and accept the parent node's UID,
    a limit for the number of items to load, a cursor for pagination,
    and arbitrary keyword arguments.
    """
    async def __call__(
            self,
            uid: UID_TYPE,
            limit: int,
            cursor: int,
            **kwargs: Any
    ) -> tuple[Optional[Sequence["PageNode"]], bool]:
        """
        Args:
            uid: The UID of the parent node for which to load children.
            limit: The maximum number of child nodes to load.
            cursor: The starting offset for loading child nodes (for pagination).
            **kwargs: Additional arguments that might be needed for loading.

        Returns:
            A tuple containing:
            - An optional sequence of PageNode objects (the loaded children).
            - A boolean indicating if there are more children to load beyond this batch.
        """
        ...

class FormatterProtocol(Protocol):
    """
    Protocol for a function that formats the text content of a PageNode.
    """
    def __call__(
            self,
            text: str,
            **kwargs: Any
    ) -> str:
        """
        Args:
            text: The original text content from PageNode.content.text.
            **kwargs: Additional keyword arguments from PageNode.content.kwargs
                      that can be used in formatting.

        Returns:
            The formatted text string.
        """
        ...

class MovePage(CallbackData, prefix="paginator"):
    """Callback data for pagination navigation."""
    action: Literal['up', 'down', 'next', 'prev', 'current']
    uid: Optional[UID_TYPE] = None

class KeyboardBuilder:
    """
    Utility class for creating and building navigation keyboards for the Paginator.
    """
    
    @staticmethod
    def create_navigation(
        page: PageNode,
        cursor: int,
        has_more: bool
    ) -> tuple[dict[str, KeyboardDataType], list[int]]:
        """
        Creates the navigation buttons and their layout sizes for a given page.

        Args:
            page: The current PageNode for which to create navigation.
            cursor: The current cursor position (offset) within the page's children.
            has_more: Boolean indicating if there are more items to load (for "next" button).

        Returns:
            A tuple containing:
            - A dictionary of navigation buttons (label: callback_data).
            - A list of integers representing the row sizes for these buttons.
        """
        keyboard: dict[str, KeyboardDataType] = {}
        sizes = []
        
        if page.children:
            # Display children as buttons
            child_keys = tuple(page.children.keys()) # Ensure consistent order
            for uid_ in child_keys[cursor:cursor+page.config.obj_count_per_page]:
                keyboard[page.children[uid_].content.label] = MovePage(action="down", uid=uid_)
            # Calculate sizes for children buttons
            num_children_on_page = len(child_keys[cursor:cursor+page.config.obj_count_per_page])
            if num_children_on_page > 0:
                # Attempt to fit 2 per row, or 1 if odd number for the last row
                sizes.extend([2] * (num_children_on_page // 2))
                if num_children_on_page % 2 == 1:
                    sizes.append(1)


        control_row_size = 0
        if cursor > 0:
            keyboard["⬅️"] = MovePage(action="prev")
            control_row_size += 1
        
        # Display page number if applicable (more than one page of children exists)
        total_children = len(page.children)
        items_per_page = page.config.obj_count_per_page
        if total_children > items_per_page: # Only show page number if multiple pages
            current_page_num = cursor // items_per_page + 1
            keyboard[f"{current_page_num}"] = MovePage(action="current")
            control_row_size +=1
        
        if has_more:
            keyboard["➡️"] = MovePage(action="next")
            control_row_size += 1
        
        if control_row_size > 0:
            sizes.append(control_row_size)
        
        if page.parent:
            keyboard["Назад"] = MovePage(action="up")
            sizes.append(1)
        
        logger.debug(f"Created navigation for page UID: {page.uid}, cursor: {cursor}, has_more: {has_more}. Nav_keys: {list(keyboard.keys())}, Sizes: {sizes}")
        return keyboard, [s for s in sizes if s > 0] # Filter out zero sizes

    @staticmethod
    def build_keyboard(
            btns: dict[str, KeyboardDataType],
            row_sizes: tuple[int, ...]
    ) -> InlineKeyboardMarkup:
        """
        Builds an InlineKeyboardMarkup from a dictionary of buttons and row sizes.

        Args:
            btns: A dictionary of buttons where keys are labels and values are callback data.
            row_sizes: A tuple defining the number of buttons per row.

        Returns:
            An Aiogram InlineKeyboardMarkup.
        """
        logger.debug(f"Building keyboard with buttons: {list(btns.keys())}, row_sizes: {row_sizes}")
        return get_callback_btns(
            btns=btns,
            sizes=row_sizes
        )

class Paginator():
    """
    Manages paginated display of hierarchical content (PageNode objects) in an Aiogram bot.

    Allows navigation through pages, loading content dynamically, and custom formatting.
    """

    def __init__(
            self,
            page: PageNode,
            loader_func: Optional[LoaderFunctionProtocol] = None,
            formatter: Optional[FormatterProtocol] = None,
            global_kbd: Optional[dict[str, KeyboardDataType]] = None
    ):
        """
        Initializes the Paginator.

        Args:
            page: The initial PageNode to display.
            loader_func: An optional global function to load child nodes if not specified
                         in PageNode.config.
            formatter: An optional global function to format text content.
            global_kbd: An optional dictionary of global keyboard buttons to be added
                        to every page's keyboard.
        """
        self.page = page
        self.cursor = 0
        self.keyboard_builder = KeyboardBuilder()
        self.loader_func: Optional[LoaderFunctionProtocol] = loader_func
        self.formatter: Optional[FormatterProtocol] = formatter
        self.global_kbd = global_kbd if global_kbd else {}
        logger.info(f"Paginator initialized for page UID: {page.uid}. Loader: {'present' if loader_func else 'absent'}, Formatter: {'present' if formatter else 'absent'}")


    async def _get_page_content(
            self,
            func: Optional[LoaderFunctionProtocol] = None,
            page: Optional[PageNode] = None,
            **kwargs: Any
    ) -> tuple[str, Optional[Image], InlineKeyboardMarkup]:
        """
        Prepares the content (text, image, keyboard) for a given page.

        Loads child nodes if necessary using the provided or default loader function.
        Constructs the navigation and custom keyboard.
        Formats the text content if a formatter is available.

        Args:
            func: Specific loader function to use for this call, overriding defaults.
            page: Specific PageNode to get content for, defaults to self.page.
            **kwargs: Additional arguments to pass to the loader function.

        Returns:
            A tuple containing:
            - The formatted text content.
            - An optional image.
            - The InlineKeyboardMarkup for the page.
        """
        target_page = page or self.page
        logger.debug(f"Getting page content for page UID: {target_page.uid}, cursor: {self.cursor}")

        chosen_func_source = "argument" if func else "self.loader_func" if self.loader_func else "self.page.config.loader_func" if target_page.config.loader_func else "None"
        logger.debug(f"Loader function source for page UID {target_page.uid}: {chosen_func_source}")
        func = func if func is not None else self.loader_func if self.loader_func else target_page.config.loader_func # Changed self.page to target_page

        async def _load_data() -> bool:
            logger.debug(f"Attempting to load data for page UID: {target_page.uid} using loader function.")
            if not func:
                logger.warning(f"No loader function available for page UID: {target_page.uid} inside _load_data.")
                return False # No loader function defined
            
            logger.debug(f"Calling loader function for UID: {target_page.uid}, limit: {target_page.config.obj_count_per_page}, current children count: {len(target_page.children)}, kwargs: {kwargs}")
            data, has_more_data = await func(target_page.uid, target_page.config.obj_count_per_page, len(target_page.children), **kwargs)
            if data:
                logger.debug(f"Loader function for UID: {target_page.uid} returned {len(data)} items. Adding children.")
                target_page.add_children(data)
            else:
                logger.debug(f"Loader function for UID: {target_page.uid} returned no new items.")
            logger.debug(f"Loader function for UID: {target_page.uid} indicates has_more_data: {has_more_data}")
            return has_more_data

        has_more_on_current_page = False
        # Check if we need to load more data only if it's not a leaf node
        if not target_page.content.is_leaf_node:
            # Calculate if there might be more items beyond what's currently loaded for this *specific display window*
            # This logic determines if the "next" button should be shown for currently *visible* items.
            # `len(target_page.children)` is the total number of *already loaded* children.
            # `self.cursor` is the start of the current view.
            # `target_page.config.obj_count_per_page` is how many items we show per view.

            # If the number of children already loaded is greater than the items displayed up to the end of the current view window
            if len(target_page.children) > self.cursor + target_page.config.obj_count_per_page:
                has_more_on_current_page = True
            # If we are at the end of the currently loaded children, try to load more
            elif self.cursor + target_page.config.obj_count_per_page >= len(target_page.children):
                 # And if loader_func exists
                if func:
                    logger.debug(f"Attempting to load more data for page UID: {target_page.uid} as cursor is near end of loaded children.")
                    has_more_on_current_page = await _load_data()
                else:
                    logger.debug(f"No loader function available to load more data for page UID: {target_page.uid} when cursor is near end.")


        nav_keyboard, nav_sizes = self.keyboard_builder.create_navigation(
            target_page, self.cursor, has_more_on_current_page
        )

        buttons = {**nav_keyboard, **target_page.custom_kbd, **self.global_kbd}
        # Ensure custom_kbd and global_kbd have their own rows if they exist
        custom_kbd_size = 1 if target_page.custom_kbd else 0
        global_kbd_size = 1 if self.global_kbd else 0
        
        final_sizes = list(nav_sizes)
        if custom_kbd_size > 0:
            final_sizes.append(custom_kbd_size) # Assuming custom buttons fit on one row or are adjusted by get_callback_btns
        if global_kbd_size > 0:
            final_sizes.append(global_kbd_size)

        markup = self.keyboard_builder.build_keyboard(
            btns=buttons,
            row_sizes=tuple(s for s in final_sizes if s > 0) # type: ignore
        )

        text_to_format = target_page.content.text
        content_text = (
            self.formatter(text=text_to_format, **target_page.content.kwargs) if self.formatter is not None else text_to_format
        )
        
        logger.debug(f"Page content prepared for UID: {target_page.uid}. Text length: {len(content_text)}, Image: {'present' if target_page.content.image else 'absent'}")
        return content_text, target_page.content.image, markup

    async def show_page(
            self,
            event: EventType,
            func: Optional[LoaderFunctionProtocol] = None,
            page: Optional[PageNode] = None,
            **kwargs: Any
    ) -> None:
        """
        Displays a page of the Paginator.

        Retrieves the content for the page (text, image, keyboard) and sends or edits
        a message to display it.

        Args:
            event: The Aiogram Message or CallbackQuery that triggered this action.
            func: Specific loader function to use, overriding defaults.
            page: Specific PageNode to show, defaults to self.page.
            **kwargs: Additional arguments to pass to the loader and formatter.
        """

        target_page = page or self.page
        logger.info(f"Showing page for UID: {target_page.uid}, event type: {type(event).__name__}")


        text, image, markup = await self._get_page_content(func=func, page=target_page, **kwargs)
        
        logger.debug(f"Attempting to send/edit message for page UID: {target_page.uid}")
        await send_or_edit_message(
            event=event,
            text=text,
            markup=markup,
            image=image
        )

    async def handle_navigation(
            self,
            event: EventType,
            callback_data: MovePage,
            **kwargs: Any
    ) -> None:
        """
        Handles navigation actions triggered by callback queries (e.g., next, prev, up, down).

        Updates the Paginator's current page (self.page) and cursor based on the
        navigation action, then calls show_page to display the new state.

        Args:
            event: The Aiogram CallbackQuery that triggered the navigation.
            callback_data: The MovePage object containing navigation action and target UID.
            **kwargs: Additional arguments to pass to show_page (and thus to loader/formatter).
        """
        
        action = callback_data.action
        uid = callback_data.uid
        
        logger.info(f"Handling navigation: action='{action}', uid='{uid}', current page UID='{self.page.uid}', cursor={self.cursor}")

        if action == "next":
            # Check if there are more items on the current level to advance the cursor
            if self.cursor + self.page.config.obj_count_per_page < len(self.page.children) or \
               (self.page.config.loader_func or self.loader_func): # Or if a loader exists to potentially load more
                self.cursor += self.page.config.obj_count_per_page
                logger.debug(f"Action 'next': new cursor {self.cursor}")
            else:
                logger.debug(f"Action 'next': no more items or loader to advance cursor. Cursor remains {self.cursor}")
        elif action == "prev":
            if self.cursor > 0:
                self.cursor = max(0, self.cursor - self.page.config.obj_count_per_page)
                logger.debug(f"Action 'prev': new cursor {self.cursor}")
            else:
                logger.debug(f"Action 'prev': cursor already at 0. Cursor remains {self.cursor}")
        elif action == "down":
            if uid is not None:
                if uid in self.page.children:
                    # target_child_page_uid = self.page.children[uid].uid # Not needed as self.page.uid will be the new page's UID
                    self.page = self.page.children[uid]
                    self.cursor = 0
                    logger.debug(f"Action 'down': Navigated to child. New current page UID: '{self.page.uid}', new cursor: {self.cursor}")
                else:
                    logger.warning(f"Action 'down': Child UID '{uid}' not found in children of page '{self.page.uid}'. No navigation.")
            else:
                logger.warning(f"Action 'down': UID is None. Cannot navigate down. Current page UID: '{self.page.uid}'")
        elif action == "up":
            if self.page.parent:
                current_page_uid_before_up = self.page.uid
                # Try to find current page in parent's children to set cursor appropriately
                parent_children_uids = list(self.page.parent.children.keys())
                try:
                    idx = parent_children_uids.index(self.page.uid)
                    # Set cursor to the page where this child would be displayed
                    self.cursor = (idx // self.page.parent.config.obj_count_per_page) * self.page.parent.config.obj_count_per_page
                except ValueError:
                    logger.warning(f"Action 'up': Current page UID '{self.page.uid}' not found in parent's children UIDs. Setting cursor to 0.")
                    self.cursor = 0 # Fallback if not found (should not happen)
                self.page = self.page.parent
                logger.debug(f"Action 'up': Navigated from '{current_page_uid_before_up}' to parent. New current page UID: '{self.page.uid}', new cursor: {self.cursor}")
            else: # Already at root, cannot go further up
                logger.debug(f"Action 'up': Already at root (page UID: '{self.page.uid}'). No navigation.")
                pass
        elif action == "current":
            logger.debug("Action 'current': Refreshing current page.")
            pass # No change in page or cursor, just refresh
        
        logger.info(f"Navigation handled. New state: page UID='{self.page.uid}', cursor={self.cursor}. Triggering show_page.")
        await self.show_page(event=event, **kwargs)