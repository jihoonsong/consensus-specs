from eth_consensus_specs.test.context import (
    spec_state_test_with_matching_config,
    with_heze_and_later,
)
from eth_consensus_specs.test.helpers.block import build_empty_block_for_next_slot
from eth_consensus_specs.test.helpers.fork_choice import get_genesis_forkchoice_store
from eth_consensus_specs.test.helpers.inclusion_list import (
    get_sample_signed_inclusion_list,
    run_with_inclusion_list_store,
)
from eth_consensus_specs.test.helpers.state import state_transition_and_sign_block


@with_heze_and_later
@spec_state_test_with_matching_config
def test_block_inclusion_list_bits_satisfaction_survives_pruning(spec, state):
    def run_scenario():
        store = get_genesis_forkchoice_store(spec, state)
        signed_inclusion_list = get_sample_signed_inclusion_list(
            spec,
            store,
            state,
            transactions=spec.Transactions(data=[spec.Transaction(data=[1])]),
        )
        spec.on_inclusion_list(store, signed_inclusion_list)
        block = build_empty_block_for_next_slot(spec, state)
        signed_block = state_transition_and_sign_block(spec, state, block)
        spec.on_tick(store, spec.compute_time_at_slot_ms(store.genesis_time_ms, block.slot))
        spec.on_block(store, signed_block)
        root = block.hash_tree_root()
        assert not spec.is_block_inclusion_list_bits_satisfied(store, root)

        slot = (
            signed_inclusion_list.message.slot
            + spec.config.MIN_SLOTS_FOR_INCLUSION_LISTS_REQUESTS
            + 1
        )
        spec.on_tick(store, spec.compute_time_at_slot_ms(store.genesis_time_ms, slot))
        inclusion_list_store = spec.get_inclusion_list_store()
        inclusion_list_store.inclusion_lists.clear()
        inclusion_list_store.equivocators.clear()

        assert not spec.is_block_inclusion_list_bits_satisfied(store, root)
        assert spec.get_head(store).root == block.parent_root

    run_with_inclusion_list_store(spec, run_scenario)
