"""Prompt transforms that compact context while preserving trace links."""

from zeta.context.compaction.drop_oldest import DropOldestPromptTransform
from zeta.context.compaction.structural_trim import StructuralTrimPromptTransform
from zeta.context.compaction.task_state import (
    TASK_STATE_SCHEMA,
    ModelTaskStateExtractor,
    TaskStateExtractionPromptTransform,
    TaskStateExtractor,
    task_state_component,
    task_state_extraction_messages,
    task_state_json,
    task_state_message,
)

__all__ = [
    "DropOldestPromptTransform",
    "ModelTaskStateExtractor",
    "StructuralTrimPromptTransform",
    "TASK_STATE_SCHEMA",
    "TaskStateExtractionPromptTransform",
    "TaskStateExtractor",
    "task_state_component",
    "task_state_extraction_messages",
    "task_state_json",
    "task_state_message",
]
