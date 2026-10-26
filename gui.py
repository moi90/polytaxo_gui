import os.path
from pprint import pprint
import re
from typing import Any, Dict, List, Optional

import nicegui
import pandas as pd
from nicegui import app, context, ui
from nicegui.elements.input import Input
from nicegui.elements.row import Row
from nicegui.elements.tree import Tree
from nicegui.elements.dialog import Dialog
from nicegui.events import ScrollEventArguments
from polytaxo import Expression, NegatedRealNode, Taxonomy, ClassNode, TagNode


class Controller:
    def __init__(self) -> None:
        print("Loading...")
        self.taxonomy = Taxonomy.from_yaml("example_data/copepod_taxonomy.yaml")

        self.taxonomy.print_tree()

        self.images = pd.read_csv("example_data/dataset_2_complete.csv")
        self.images["image_fn"] = self.images["image_fn"].map(
            lambda fn: os.path.relpath(
                fn,
                "/data1/mschroeder/22-MAZE-DL/data/LOKI_Calanus_Metridia_morpho_structure/images_all/",
            )
        )

        self.images["polytaxo_description"] = self.images["polytaxo_description"].map(
            self.taxonomy.parse_description  # type: ignore
        )  # type: ignore

        self._filtered_images = None
        self._filtered_images_offset = 0

        print("Done.")

        self.expression = self.taxonomy.parse_expression("")

        self.query_expression_element: Optional[Input] = None
        self._tree_element: Optional[Tree] = None
        self._image_container: Optional[Row] = None
        self.image_dialog: Optional[Dialog] = None

    @property
    def tree_element(self):
        return self._tree_element

    @tree_element.setter
    def tree_element(self, tree_element: Tree):
        self._tree_element = tree_element

        self.update_tree()

    @property
    def image_container(self):
        return self._image_container

    @image_container.setter
    def image_container(self, image_container):
        self._image_container = image_container

        self.update_images()

    def append_images(self, n=100):
        assert self._image_container is not None
        assert self._filtered_images is not None

        with self._image_container:
            max_offset = min(
                len(self._filtered_images) - 1, self._filtered_images_offset + n
            )
            while self._filtered_images_offset < max_offset:
                info = self._filtered_images.loc[self._filtered_images_offset].to_dict()
                with (
                    ui
                    .image(f"/example_data/{info['image_fn']}")
                    .classes("w-48 h-48")
                    .props("fit='contain' draggable")
                    .on("dblclick", lambda info=info: self.open_image_dialog(info))
                    .on(
                        "dragstart",
                        js_handler="(evt) => {evt.dataTransfer.setData('image_fn', '"
                        + info["image_fn"]
                        + "');}",
                    )
                ):
                    ui.tooltip(f"{info['polytaxo_description']}").props(
                        "anchor='top middle' offset=[0,0]"
                    )

                    # Display a context menu to edit descriptors
                    # TODO: This should show the opposite of all descriptors in the query expression
                    with ui.context_menu():
                        ui.label("Click to add properties:")
                        for descriptor in info["polytaxo_description"].descriptors:
                            if isinstance(descriptor, NegatedRealNode):
                                descriptor = descriptor.node
                            if not isinstance(descriptor, (ClassNode, TagNode)):
                                continue

                            with ui.row():
                                for n in descriptor.lineage:
                                    if not isinstance(n, descriptor.__class__):
                                        continue
                                    if n == self.taxonomy.root:
                                        continue
                                    ui.label(f"!{n.name}")
                        ui.separator()
                        ui.menu_item(
                            "Show images with the same description",
                            on_click=lambda: self.update_expression(
                                Expression(
                                    info["polytaxo_description"],
                                    exclude=self.expression.exclude,
                                ),
                                update_string=True,
                            ),
                        )

                self._filtered_images_offset += 1

    def open_image_dialog(self, image_info):
        """Open a dialog to edit an image's metadata."""

        assert self.image_dialog is not None

        self.image_dialog.clear()
        with self.image_dialog, ui.card():
            ui.image(f"/example_data/{image_info['image_fn']}").classes("min-w-96")
            with ui.card_section().classes("w-full") as section:
                ui.input("Filename:", value=str(image_info["image_fn"])).props(
                    "readonly"
                )
                ui.textarea(
                    "Description:", value=str(image_info["polytaxo_description"])
                )

                ui.separator()

                # TODO: Save changes
                ui.button("Close", on_click=self.image_dialog.close).classes("w-full")

            section.style("max-height: 50vh").classes("scroll")

        self.image_dialog.open()

    def update_images(self):
        assert self._image_container is not None
        self._image_container.clear()

        filtered_images = self.images[
            self.images["polytaxo_description"].map(self.expression.match)
        ]

        # # TODO: Implement sorting
        # if self.expression.query is not None:
        #     ui.notify("Sorting not implemented yet.")
        #     # filtered_images = filtered_images.sort_values(
        #     #     by="polytaxo_description", key=..., ascending=False
        #     # )

        self._filtered_images = filtered_images.reset_index()

        self._filtered_images_offset = 0

        self.append_images()

    def build_tree_data(self, node: ClassNode | TagNode) -> Dict[str, Any]:
        total_num_objs = (node <= self.images["polytaxo_description"]).sum()  # type: ignore
        filtered_num_objs = (
            (node <= self._filtered_images["polytaxo_description"]).sum()  # type: ignore
            if self._filtered_images is not None
            else total_num_objs
        )
        name = "/" if node.parent is None else node.name

        state_class = {
            "include": "text-bold",
            "include-negate": "text-strike",
            "exclude": "text-strike",
        }

        state = (
            "include"
            if node <= self.expression.include
            else (
                "include-negate"
                if ~node <= self.expression.include
                else (
                    "exclude"
                    if node in self.expression.exclude
                    else ("exclude-negate" if ~node in self.expression.exclude else "")
                )
            )
        )

        if isinstance(node, ClassNode):
            return {
                "id": node.format(),
                "name": name,
                "children": [
                    self.build_tree_data(c)
                    for c in sorted(node.classes, key=lambda c: c.name)
                ]
                + [
                    self.build_tree_data(c)
                    for c in sorted(node.tags, key=lambda c: c.name)
                ],
                "class": state_class.get(state, ""),
                "stats": f"{filtered_num_objs:,d} / {total_num_objs:,d}",
                "icon": "folder",
                "state": state,
            }

        if isinstance(node, TagNode):
            return {
                "id": node.format(),
                "name": name,
                "children": [self.build_tree_data(c) for c in node.tags],
                "class": state_class.get(state, ""),
                "stats": f"{filtered_num_objs:,d} / {total_num_objs:,d}",
                "icon": "more",
                "state": state,
            }

        raise ValueError()

    def update_tree(self):
        assert self._tree_element is not None

        nodes = [self.build_tree_data(self.taxonomy.root)]

        self._tree_element._props["nodes"] = nodes
        self._tree_element.update()
        self._tree_element.expand([
            n.format()
            for descriptor in self.expression.include.descriptors
            if isinstance(descriptor, (ClassNode, TagNode))
            for n in descriptor.lineage
        ])

    def on_submit_query_expression_str(self):
        assert self.query_expression_element is not None

        try:
            expression = self.taxonomy.parse_expression(
                self.query_expression_element.value
            )
        except Exception as exc:
            self.query_expression_element.props["error"] = str(exc).split("\n")[0]
            return

        self.query_expression_element.props["error"] = None

        self.update_expression(expression, False)

    def validate_expression_str(self, expression_str: str):
        assert self.query_expression_element is not None

        try:
            self.taxonomy.parse_expression(expression_str)
        except Exception as exc:
            return str(exc).split("\n")[0]

            # # TODO: One day, we could do autocomplete
            # self.expression_input.set_autocomplete([f"{expression} Foo", f"{expression} Baz"])

    def update_expression(self, expression: Expression, update_string=False):
        if self.expression != expression or update_string:
            self.expression = expression
            self.update_images()
            self.update_tree()

            if update_string:
                assert self.query_expression_element is not None
                self.query_expression_element.set_value(str(expression))

    def add_descriptor(self, id, modifier):
        # TODO: This does not work for tags. Implement `get_node`.
        path = re.split("/|:", id)[1:]
        node = self.taxonomy.root.find_real_node(path)
        # ui.notify(f"{id}: {modifier}")

        if modifier == "include":
            self.expression.include.add(node)
        elif modifier == "include-negate":
            self.expression.include.add(~node)
        elif modifier == "exclude-negate":
            self.expression.exclude.append(~node)
        else:
            raise ValueError(modifier)

        self.update_expression(self.expression, update_string=True)

    def handle_drop_image_on_tree(self, image_fn, node_id):
        # TODO: Update description of image
        ui.notify(f"Dropped {image_fn} on {node_id}")


class three_way_splitter:
    """Reusable component that creates a three-way splitter layout with left, middle, and right sections."""

    def __init__(self):
        self._left_splitter_prev_value = 20
        self._right_splitter_prev_value = 20

        self.left_splitter = ui.splitter(value=20).classes("w-full h-full")
        with self.left_splitter.after:
            self.right_splitter = ui.splitter(value=20, reverse=True).classes(
                "w-full h-full"
            )

        self._add_splitter_toggle(
            self.left_splitter,
            prev_value_attr="_left_splitter_prev_value",
            open_icon="keyboard_double_arrow_left",
            collapsed_icon="keyboard_double_arrow_right",
        )
        self._add_splitter_toggle(
            self.right_splitter,
            prev_value_attr="_right_splitter_prev_value",
            open_icon="keyboard_double_arrow_right",
            collapsed_icon="keyboard_double_arrow_left",
        )

    @staticmethod
    def _splitter_icon_name(value: float, open_icon: str, collapsed_icon: str) -> str:
        return collapsed_icon if value < 1 else open_icon

    def _add_splitter_toggle(
        self,
        splitter: ui.splitter,
        *,
        prev_value_attr: str,
        open_icon: str,
        collapsed_icon: str,
    ) -> None:
        with splitter.separator:
            with (
                ui
                .button(color="secondary")
                .classes("p-0")
                .props("round")
                .on_click(lambda: self._toggle_splitter(splitter, prev_value_attr))
            ):
                icon = ui.icon(
                    self._splitter_icon_name(splitter.value, open_icon, collapsed_icon)
                )

        splitter.on_value_change(
            lambda e, icon=icon: icon.set_name(
                self._splitter_icon_name(e.value, open_icon, collapsed_icon)
            )
        )

    def _toggle_splitter(self, splitter, prev_value_attr: str) -> None:
        if splitter.value < 1:
            splitter.value = getattr(self, prev_value_attr)
        else:
            setattr(self, prev_value_attr, splitter.value)
            splitter.value = 0

    @property
    def left(self):
        return self.left_splitter.before

    @property
    def middle(self):
        return self.right_splitter.before

    @property
    def right(self):
        return self.right_splitter.after


@ui.page("/")
async def page():
    controller = Controller()

    context.client.content.classes("h-[calc(100vh-82px)] p-0")
    app.add_static_files("/example_data", "example_data")

    ui.add_css(
        """
    .hover-strike:hover {
        text-decoration: line-through;
    }
    """
    )

    dark = ui.dark_mode(value=app.storage.user.get("dark_mode", False)).bind_value(
        app.storage.user, "dark_mode"
    )

    with ui.header():
        ui.label("PolyTaxo").classes("text-h3")
        # ui.space()
        # ui.button("Save")
        ui.space()
        ui.button("☼/☾", on_click=dark.toggle)

    _three_way_splitter = three_way_splitter()

    with _three_way_splitter.left:
        with ui.row().classes("w-full h-16"):
            pass

        with ui.scroll_area().classes("h-full"):
            controller.tree_element = tree = ui.tree([]).props("no-transition")
            tree.add_slot(
                "default-header",
                """
                <span
                    :props="props"
                    @drop.prevent="props.tree.$emit('item-drop', $event.dataTransfer.getData('image_fn'), props.node.id)"
                    @dragover.prevent
                    @dragenter.prevent>
                        <i class="q-icon notranslate material-icons-outlined" aria-hidden="true" role="presentation" id="c6">{{ props.node.icon }}</i>
                        <span :class="props.node.class">{{ props.node.name }}</span>
                        (<span class="text-italic">{{ props.node.stats }}</span>)
                </span>
                """,
            )
            tree.add_slot(
                "default-body",
                """
                <q-btn-toggle
                    v-model="props.node.state"
                    push
                    rounded
                    clearable
                    toggle-color="primary"
                    :options="[
                    {label: '✓', value: 'include'},
                    {label: '!', value: 'include-negate'},
                    {label: '-', value: 'exclude'},
                    {label: '-!', value: 'exclude-negate'},
                    ]"
                    @click="props.tree.$emit('item-click', props.node.id, props.node.state)"
                    v-if="props.node.name != '/'"
                />
                """,
            )
            tree.on("item-click", lambda e: controller.add_descriptor(*e.args))
            tree.on(
                "item-drop", lambda e: controller.handle_drop_image_on_tree(*e.args)
            )

        with _three_way_splitter.middle:
            with ui.row().classes("w-full h-16"):
                # controller.expression_element = (
                #     ui.select(
                #         [],
                #         label="Query Expression",
                #         with_input=True,
                #     )
                #     .classes("w-full")
                #     .on("input-value", lambda e: print(e.args), throttle=0.1)
                # )

                # TODO: Implement '?' query modifier to sort results
                controller.query_expression_element = (
                    ui
                    .input(
                        label="Query Expression",
                        validation=controller.validate_expression_str,
                    )
                    .classes("w-full")
                    .on("keydown.enter", controller.on_submit_query_expression_str)
                )
                with controller.query_expression_element:
                    ui.button(
                        on_click=controller.on_submit_query_expression_str,
                        icon="check",
                    ).props("flat dense")

            def handle_scroll(event: ScrollEventArguments):
                if (
                    event.vertical_position + event.vertical_container_size
                    >= event.vertical_size - 200
                ):
                    controller.append_images(20)

            with ui.scroll_area().classes("h-full").on_scroll(handle_scroll):
                controller.image_container = ui.row()

            controller.image_dialog = ui.dialog()

        with _three_way_splitter.right:
            with ui.row().classes("w-full h-16"):
                pass

            with ui.scroll_area().classes("h-full"):
                ui.label("Right panel").classes(
                    "text-h6 text-center text-grey-5 w-full"
                ).style("margin-top: 50%")


# TODO: Make storage_secret configurable
ui.run(title="PolyTaxo", show=False, storage_secret="dummy_secret")
