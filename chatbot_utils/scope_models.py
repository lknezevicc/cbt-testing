from enum import Enum
from typing import Any, Dict, List, Optional, Union


class Sample:
    def __init__(self, text: str):
        self.text = text

    def __str__(self) -> str:
        return f"Sample(text={self.text})"


class VariableType(Enum):
    ENUM = "enum"
    TEXT = "text"
    BOOLEAN = "boolean"
    NUMBER = "number"
    OBJECT = "object"
    CONFIRMATION = "confirmation"


class Variable:
    def __init__(
        self,
        name: str,
        type: Optional[VariableType] = None,
        value: Optional[Union[str, bool, int, float, list, dict]] = None,
    ):
        self.name = name
        self.type = type
        self.value = value

    def __str__(self) -> str:
        return f"Variable(name={self.name}, type={self.type}, value={self.value})"


class Override:
    def __init__(
        self,
        name: str,
        ask_override: Optional[List[Any]] = None,
        input_error_ask_override: Optional[List[Any]] = None,
        validation_error_ask_override: Optional[List[Any]] = None,
        validation_actions_override: Optional[List[Any]] = None,
        correction_answer_override: Optional[List[Any]] = None,
    ):
        self.name = name
        self.ask_override = ask_override or []
        self.input_error_ask_override = input_error_ask_override or []
        self.validation_error_ask_override = validation_error_ask_override or []
        self.validation_actions_override = validation_actions_override or []
        self.correction_answer_override = correction_answer_override or []

    def __str__(self) -> str:
        return (
            f"Override(name={self.name}, ask_override={self.ask_override}, "
            f"input_error_ask_override={self.input_error_ask_override}, "
            f"validation_error_ask_override={self.validation_error_ask_override}, "
            f"validation_actions_override={self.validation_actions_override}, "
            f"correction_answer_override={self.correction_answer_override})"
        )


class ContextVariable(Override):
    def __str__(self) -> str:
        return f"ContextVariable({super().__str__()})"


class Button:
    def __init__(self, title: Optional[str] = None, payload: Optional[str] = None):
        self.title = title
        self.payload = payload

    def __str__(self) -> str:
        return f"Button(title={self.title}, payload={self.payload})"


class Answer:
    def __init__(
        self,
        text: Optional[str] = None,
        buttons: Optional[List[Button]] = None,
        conditions: Optional[List[Any]] = None,
    ):
        self.text = text
        self.buttons = buttons or []
        self.conditions = conditions or []

    def __str__(self) -> str:
        return f"Answer(text={self.text}, buttons={self.buttons}, conditions={self.conditions})"


class Dialog:
    def __init__(
        self,
        id: str,
        name: str,
        topic: str,
        answers: List[Answer],
        overrides: Dict[str, Override],
        samples: List[Sample],
        description: str,
        follow_up_dialog: Optional[Any] = None,
        is_active: bool = True,
        is_routable: bool = True,
        is_blocking: bool = False,
        is_returnable: bool = True,
        is_persistent: bool = True,
        is_excluded_from_clarification: bool = False,
    ):
        self.id = id
        self.name = name
        self.topic = topic
        self.answers = answers
        self.overrides = overrides
        self.samples = samples
        self.description = description
        self.follow_up_dialog = follow_up_dialog
        self.is_active = is_active
        self.is_routable = is_routable
        self.is_blocking = is_blocking
        self.is_returnable = is_returnable
        self.is_persistent = is_persistent
        self.is_excluded_from_clarification = is_excluded_from_clarification

    def __str__(self) -> str:
        return (
            f"Dialog(id={self.id}, name={self.name}, topic={self.topic}, "
            f"answers={self.answers}, overrides={self.overrides}, samples={self.samples}, "
            f"description={self.description}, follow_up_dialog={self.follow_up_dialog}, "
            f"is_active={self.is_active}, is_routable={self.is_routable}, "
            f"is_blocking={self.is_blocking}, is_returnable={self.is_returnable}, "
            f"is_persistent={self.is_persistent}, "
            f"is_excluded_from_clarification={self.is_excluded_from_clarification})"
        )


def parse_yaml_to_dialog(data: dict) -> Dialog:
    data = data.get("dialogs", {})
    name, dialog_definition = next(iter(data.items()))

    routable_value = dialog_definition.get("routable", dialog_definition.get("is_routable", True))

    return Dialog(
        id=dialog_definition.get("id", name),
        name=dialog_definition.get("name", name),
        topic=dialog_definition.get("topic", ""),
        answers=[parse_yaml_to_answer(a) for a in dialog_definition.get("answers", [])],
        overrides={
            k: parse_yaml_to_override(v)
            for k, v in dialog_definition.get("overrides", {}).items()
        },
        samples=[Sample(text=s) for s in dialog_definition.get("samples", [])],
        description=dialog_definition.get("description", ""),
        follow_up_dialog=None,
        is_active=dialog_definition.get("is_active", True),
        is_routable=bool(routable_value),
        is_blocking=dialog_definition.get("is_blocking", False),
        is_returnable=dialog_definition.get("is_returnable", True),
        is_persistent=dialog_definition.get("is_persistent", True),
        is_excluded_from_clarification=dialog_definition.get(
            "is_excluded_from_clarification", False
        ),
    )


def parse_yaml_to_answer(data: dict) -> Answer:
    buttons_data = data.get("buttons", [])
    buttons = [parse_yaml_to_button(btn) for btn in buttons_data]

    return Answer(
        text=data.get("text", None),
        buttons=buttons,
        conditions=data.get("condition", []),
    )


def parse_yaml_to_button(data: dict) -> Button:
    return Button(
        title=data.get("title", None),
        payload=data.get("payload", None),
    )


def parse_yaml_to_override(data: dict) -> Override:
    return Override(
        name=data.get("name", ""),
        ask_override=[],
        input_error_ask_override=[],
        validation_error_ask_override=[],
        validation_actions_override=[],
        correction_answer_override=[],
    )
