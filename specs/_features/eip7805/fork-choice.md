# EIP-7805 -- Fork Choice

## Table of contents
<!-- TOC -->
<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Introduction](#introduction)
- [Configuration](#configuration)
- [Helpers](#helpers)
  - [New `validate_inclusion_lists`](#new-validate_inclusion_lists)
  - [Modified `Store`](#modified-store)
      - [Modified `notify_new_payload`](#modified-notify_new_payload)
      - [`get_attester_head`](#get_attester_head)
  - [New `on_inclusion_list`](#new-on_inclusion_list)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->
<!-- /TOC -->

## Introduction

This is the modification of the fork choice accompanying the EIP-7805 upgrade.

## Configuration

| Name | Value | Unit | Duration |
| - | - | :-: | :-: |
| `VIEW_FREEZE_DEADLINE` | `uint64(9)` | seconds | 9 seconds  # (New in EIP7805) | 

## Helpers

### New `validate_inclusion_lists`

```python
def validate_inclusion_lists(store: Store, inclusion_list_transactions: List[Transaction, MAX_TRANSACTIONS_PER_INCLUSION_LIST * IL_COMMITTEE_SIZE], execution_payload: ExecutionPayload) -> bool:
    """
    Return ``True`` if and only if the input ``inclusion_list_transactions`` satisfies validation,
    that to verify if the ``execution_payload`` satisfies ``inclusion_list_transactions`` validity conditions either when all transactions are present in payload or 
    when any missing transactions are found to be invalid when appended to the end of the payload unless the block is full.
    """
    ...
```

### Modified `Store` 

**Note:** `Store` is modified to track the seen inclusion lists and inclusion list equivocators.

```python
@dataclass
class Store(object):
    time: uint64
    genesis_time: uint64
    justified_checkpoint: Checkpoint
    finalized_checkpoint: Checkpoint
    unrealized_justified_checkpoint: Checkpoint
    unrealized_finalized_checkpoint: Checkpoint
    proposer_boost_root: Root
    equivocating_indices: Set[ValidatorIndex]
    blocks: Dict[Root, BeaconBlock] = field(default_factory=dict)
    block_states: Dict[Root, BeaconState] = field(default_factory=dict)
    block_timeliness: Dict[Root, boolean] = field(default_factory=dict)
    checkpoint_states: Dict[Checkpoint, BeaconState] = field(default_factory=dict)
    latest_messages: Dict[ValidatorIndex, LatestMessage] = field(default_factory=dict)
    unrealized_justifications: Dict[Root, Checkpoint] = field(default_factory=dict)
    inclusion_lists: Dict[Tuple[Slot, Root], List[InclusionList]] = field(default_factory=dict) # [New in EIP-7805]
    inclusion_list_equivocators: Dict[Tuple[Slot, Root], Set[ValidatorIndex]] = field(default_factory=dict) # [New in EIP-7805]
    unsatisfied_inclusion_list_blocks: Set[Root] # [New in EIP-7805]
```

##### Modified `notify_new_payload`

*Note*: The function `notify_new_payload` is modified to include the additional `il_transactions` parameter in EIP-7805.

```python
def notify_new_payload(self: ExecutionEngine,
                       execution_payload: ExecutionPayload,
                       execution_requests: ExecutionRequests,
                       parent_beacon_block_root: Root,
                       il_transactions: List[Transaction, MAX_TRANSACTIONS_PER_INCLUSION_LIST],
                       store: Store) -> bool:
    """
    Return ``True`` if and only if ``execution_payload`` and ``execution_requests`` 
    are valid with respect to ``self.execution_state``.
    """
    
    # If execution client returns block does not satisfy inclusion list transactions, cache the block
    store.unsatisfied_inclusion_list_blocks.add(execution_payload.block_root)
    ...
```

##### `get_attester_head`

```python
def get_attester_head(store: Store, head_root: Root) -> Root:
  head_block = store.blocks[head_root]
  
  if head_root in store.unsatisfied_inclusion_list_blocks:
    return head_block.parent_root
  return head_root

```

### New `on_inclusion_list`

`on_inclusion_list` is called to import `signed_inclusion_list` to the fork choice store.

```python
def on_inclusion_list(
        store: Store, 
        signed_inclusion_list: SignedInclusionList, 
        inclusion_list_committee: Vector[ValidatorIndex, IL_COMMITTEE_SIZE]]) -> None:
    """
    Verify the inclusion list and import it into the fork choice store.
    If there exists more than 1 inclusion list in store with the same slot and validator index, add the equivocator to the ``inclusion_list_equivocators`` cache.
    Otherwise, add inclusion list to the ``inclusion_lists` cache.
    """
    message = signed_inclusion_list.message
    # Verify inclusion list slot is either from the current or previous slot
    assert get_current_slot(store) in [message.slot, message.slot + 1]

    time_into_slot = (store.time - store.genesis_time) % SECONDS_PER_SLOT
    is_before_attesting_interval = time_into_slot < SECONDS_PER_SLOT // INTERVALS_PER_SLOT
    # If the inclusion list is from the previous slot, ignore it if already past the attestation deadline
    if get_current_slot(store) == message.slot + 1:
        assert is_before_attesting_interval

    # Sanity check that the given `inclusion_list_committee` matches the root in the inclusion list
    root = message.inclusion_list_committee_root
    assert hash_tree_root(inclusion_list_committee) == root

    # Verify inclusion list validator is part of the committee
    validator_index = message.validator_index
    assert validator_index in inclusion_list_committee
   
    # Verify inclusion list signature
    assert is_valid_inclusion_list_signature(state, signed_inclusion_list)

    is_before_freeze_deadline = get_current_slot(store) == message.slot and time_into_slot < VIEW_FREEZE_DEADLINE

    # Do not process inclusion lists from known equivocators
    if validator_index not in inclusion_list_equivocators[(message.slot, root)]:
        if validator_index in [il.validator_index for il in inclusion_lists[(message.slot, root)]]:
            il = [il for il in inclusion_lists[(message.slot, root)] if il.validator_index == validator_index][0]
            if validator_il != message:
                # We have equivocation evidence for `validator_index`, record it as equivocator
                inclusion_list_equivocators[(message.slot, root)].add(validator_index)
        # This inclusion list is not an equivocation. Store it if prior to the view freeze deadline
        elif is_before_freeze_deadline:
            inclusion_lists[(message.slot, root)].append(message)
```

