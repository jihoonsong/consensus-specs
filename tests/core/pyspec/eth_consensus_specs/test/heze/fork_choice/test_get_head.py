from eth_utils import encode_hex

from eth_consensus_specs.test.context import (
    spec_state_test_with_matching_config,
    with_heze_and_later,
)
from eth_consensus_specs.test.helpers.block import build_empty_block_for_next_slot
from eth_consensus_specs.test.helpers.execution_payload import (
    build_signed_execution_payload_envelope,
)
from eth_consensus_specs.test.helpers.fork_choice import (
    add_execution_payload,
    get_genesis_forkchoice_store_and_block,
    on_tick_and_append_step,
    output_head_check,
    tick_and_add_block,
    tick_store_to_slot,
)
from eth_consensus_specs.test.helpers.inclusion_list import (
    get_sample_signed_inclusion_list,
    run_with_inclusion_list_store,
)
from eth_consensus_specs.test.helpers.state import state_transition_and_sign_block


def _run_get_head_with_inclusion_list(
    spec,
    state,
    *,
    inclusive=False,
    timely=True,
    advance_slot=False,
    full_parent=False,
    inclusive_sibling=False,
):
    def run_scenario():
        test_steps = []
        store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
        yield "anchor_state", state.copy()
        yield "anchor_block", anchor_block

        parent = build_empty_block_for_next_slot(spec, state)
        signed_parent = state_transition_and_sign_block(spec, state, parent)
        yield from tick_and_add_block(spec, store, signed_parent, test_steps)
        if full_parent:
            parent_root = signed_parent.message.hash_tree_root()
            envelope = build_signed_execution_payload_envelope(
                spec, state, parent_root, signed_parent
            )
            yield from add_execution_payload(spec, store, envelope, test_steps)

        signed_inclusion_list = get_sample_signed_inclusion_list(
            spec,
            store,
            state,
            transactions=spec.Transactions(data=[spec.Transaction(data=[1])]),
        )
        if not timely:
            due_seconds = spec.milliseconds_to_seconds(spec.get_inclusion_list_due_ms()) + 1
            on_tick_and_append_step(
                spec, store, store.time_ms + spec.seconds_to_milliseconds(due_seconds), test_steps
            )
        spec.on_inclusion_list(store, signed_inclusion_list)
        file_name = f"inclusion_list_{encode_hex(signed_inclusion_list.hash_tree_root())}"
        yield file_name, signed_inclusion_list
        test_steps.append({"inclusion_list": file_name})

        block = build_empty_block_for_next_slot(spec, state)
        if full_parent:
            block.body.signed_execution_payload_bid.message.parent_block_hash = (
                parent.body.signed_execution_payload_bid.message.block_hash
            )
            block.body.signed_execution_payload_bid.message.block_hash = spec.Hash32(b"\x42" * 32)
        if inclusive or inclusive_sibling:
            committee = spec.get_inclusion_list_committee(state, signed_inclusion_list.message.slot)
            inclusion_list_bits = spec.InclusionListBits(
                data=[index == signed_inclusion_list.message.validator_index for index in committee]
            )
            if inclusive:
                block.body.signed_execution_payload_bid.message.inclusion_list_bits = (
                    inclusion_list_bits
                )
        signed_block = state_transition_and_sign_block(spec, state, block)
        yield from tick_and_add_block(spec, store, signed_block, test_steps)

        if inclusive_sibling:
            sibling = block.copy()
            sibling.body.signed_execution_payload_bid.message.inclusion_list_bits = (
                inclusion_list_bits
            )
            sibling_state = store.block_states[block.parent_root].copy()
            signed_sibling = state_transition_and_sign_block(spec, sibling_state, sibling)
            yield from tick_and_add_block(spec, store, signed_sibling, test_steps)

        if advance_slot:
            tick_store_to_slot(spec, store, block.slot + 1, test_steps)

        expected_root = (
            signed_block.message.hash_tree_root() if inclusive or not timely else block.parent_root
        )
        head = spec.get_head(store)
        assert head.root == expected_root
        expected_payload_status = (
            spec.PAYLOAD_STATUS_FULL
            if full_parent and not inclusive and timely
            else spec.PAYLOAD_STATUS_EMPTY
        )
        assert head.payload_status == expected_payload_status
        output_head_check(spec, store, test_steps)
        yield "steps", test_steps

    parts = []
    run_with_inclusion_list_store(spec, lambda: parts.extend(run_scenario()))
    yield from parts


@with_heze_and_later
@spec_state_test_with_matching_config
def test_get_head_reorgs_non_inclusive_block(spec, state):
    """A block omitting a timely inclusion list is replaced by its beacon parent."""
    yield from _run_get_head_with_inclusion_list(spec, state)


@with_heze_and_later
@spec_state_test_with_matching_config
def test_get_head_keeps_inclusive_block(spec, state):
    """A block marking every position of the observed includer remains the head."""
    yield from _run_get_head_with_inclusion_list(spec, state, inclusive=True)


@with_heze_and_later
@spec_state_test_with_matching_config
def test_get_head_ignores_untimely_inclusion_list(spec, state):
    """An inclusion list received after its deadline does not require a marked bit."""
    yield from _run_get_head_with_inclusion_list(spec, state, timely=False)


@with_heze_and_later
@spec_state_test_with_matching_config
def test_get_head_reorgs_previous_slot_non_inclusive_block(spec, state):
    """A missed slot does not make the previous non-inclusive block eligible."""
    yield from _run_get_head_with_inclusion_list(spec, state, advance_slot=True)


@with_heze_and_later
@spec_state_test_with_matching_config
def test_get_head_keeps_previous_slot_inclusive_block(spec, state):
    """An inclusive block remains the head when the next slot is missed."""
    yield from _run_get_head_with_inclusion_list(spec, state, inclusive=True, advance_slot=True)


@with_heze_and_later
@spec_state_test_with_matching_config
def test_get_head_reorg_preserves_full_parent(spec, state):
    """Reorging a non-inclusive block retains its verified parent payload."""
    yield from _run_get_head_with_inclusion_list(spec, state, full_parent=True)


@with_heze_and_later
@spec_state_test_with_matching_config
def test_get_head_reorgs_selected_non_inclusive_block(spec, state):
    """Reorg the selected block to its parent even when an inclusive sibling is known."""
    yield from _run_get_head_with_inclusion_list(spec, state, inclusive_sibling=True)


@with_heze_and_later
@spec_state_test_with_matching_config
def test_get_head_reorgs_consecutive_non_inclusive_blocks(spec, state):
    """Consecutive non-inclusive blocks fall back to the previous inclusive head."""

    def run_scenario():
        test_steps = []
        store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
        yield "anchor_state", state.copy()
        yield "anchor_block", anchor_block

        for _ in range(2):
            signed_inclusion_list = get_sample_signed_inclusion_list(
                spec,
                store,
                state,
                transactions=spec.Transactions(data=[spec.Transaction(data=[1])]),
            )
            spec.on_inclusion_list(store, signed_inclusion_list)
            file_name = f"inclusion_list_{encode_hex(signed_inclusion_list.hash_tree_root())}"
            yield file_name, signed_inclusion_list
            test_steps.append({"inclusion_list": file_name})

            block = build_empty_block_for_next_slot(spec, state)
            signed_block = state_transition_and_sign_block(spec, state, block)
            yield from tick_and_add_block(spec, store, signed_block, test_steps)

        head = spec.get_head(store)
        assert head.root == anchor_block.hash_tree_root()
        assert head.payload_status == spec.PAYLOAD_STATUS_EMPTY
        output_head_check(spec, store, test_steps)
        yield "steps", test_steps

    parts = []
    run_with_inclusion_list_store(spec, lambda: parts.extend(run_scenario()))
    yield from parts
