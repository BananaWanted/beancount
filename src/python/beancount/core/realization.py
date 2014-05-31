"""Realization of specific lists of account postings into reports.

This code converts a list of entries into a tree of RealAccount nodes (which
stands for "realized accounts"). The RealAccount objects contain lists of
Posting instances instead of Transactions, or other entry types that are
attached to an account, such as a Balance or Note entry.

The interface of RealAccount corresponds to that of a regular Python dict, where
the keys are the names of the individual components of an account's name, and
the values are always other RealAccount instances. If you want to get an account
by long account name, there are helper functions in this module for this purpose
(see realization.get(), for instance). RealAccount instances also contain the
final balance of that account, resulting from its list of postings.

You should not build RealAccount trees yourself; instead, you should filter the
list of desired directives to display and call the realize() function with them.
"""

import sys
from itertools import chain, repeat
from collections import OrderedDict
import collections
import operator
import copy
import itertools

from beancount.core import inventory
from beancount.core.amount import amount_sortkey
from beancount.utils import misc_utils
from beancount.core import data
from beancount.core.data import Transaction, Balance, Open, Close, Pad, Note, Document
from beancount.core.data import Posting
from beancount.core.account import account_name_leaf, account_name_parent
from beancount.core import account
from beancount.utils import tree_utils


__plan__ = """
X  fullname       -> renames to .account, which is the full name of the account, we never need the leaf name
X  balance        -> (stays the same.)
X  postings       -> (stays the same.)
X  children       -> becomes .values() from dict interface
X  asdict()       -> becomes the object itself, not really needed anymore.
X  __getitem__    -> should work as keys(), not deep. Deep uses go to get_deep_item()
X  add(account)   -> inserts leaf name automatically, not needed anymore, only used here.
X  __iter__       -> delete, just becomes keys() like dict
X  __contains__   -> remove support for recursive, onyl work on direct children, use
X  get_children() -> Remove and replace by values() usage.

FIXME: Finish supporting ra.copy(), there's a test for it.


Note: maybe these are all module functions with simple names...
X  realization.get(key, None) instead.
X  realization.set(real_account): automatically creates the intervening nodes
X  realization.contains(account_name)
X  realization.iter(real_account)
X  values_recursively -> provide a function instead, iter_children()


tree_utils should be converted to work on dicts of dicts just like this one, or maybe removed.

Maybe redefine equality to include the balance and account name? Not sure.


FIXME: document how this type works and the symmetries with dict.

"""

class RealAccount(dict):
    """A realized account, inserted in a tree, that contains the list of realized entries.

    Attributes:
      account: A string, the full name of the corresponding account.
      postings: A list of postings associated with this accounting (does not
        include the postings of children accounts).
      balance: The final balance of the list of postings associated with this account.
    """
    __slots__ = ('account', 'postings', 'balance')

    def __init__(self, account_name, *args, **kwargs):
        """Create a RealAccount instance.

        Args:
          account_name: a string, the name of the account. Maybe not be None.
        """
        super().__init__(*args, **kwargs)
        assert isinstance(account_name, str)
        self.account = account_name
        self.postings = []
        self.balance = inventory.Inventory()

    def __setitem__(self, key, value):
        """Prevent the setting of non-string or non-empty keys on this dict.

        Args:
          key: The dictionary key. Must be a string.
          value: The value, must be a RealAccount instance.
        Raises:
          KeyError: If the key is not a string, or is invalid.
          ValueError: If the value is not a RealAccount instance.
        """
        if not isinstance(key, str) or not key:
            raise KeyError("Invalid RealAccount key: '{}'".format(key))
        if not isinstance(value, RealAccount):
            raise ValueError("Invalid RealAccount value: '{}'".format(value))
        if not value.account.endswith(key):
            raise ValueError("RealAccount name '{}' inconsistent with key: '{}'".format(
                value.account, key))
        return super().__setitem__(key, value)

    def copy(self):
        """Override dict.copy() to clone a RealAccount.

        This is only necessary to correctly implement the copy method.
        Otherwise, calling .copy() on a RealAccount instance invokes the base
        class' method, which return just a dict.

        Returns:
          A cloned instance of RealAccount, with all members shallow-copied.
        """
        return copy.copy(self)

    def __eq__(self, other):
        """Equality predicate. All attributes are compared.

        Args:
          other: Another instance of RealAccount.
        Returns:
          A boolean, True if the two real accounts are equal.
        """
        return (dict.__eq__(self, other) and
                self.account == other.account and
                self.balance == other.balance and
                self.postings == other.postings)

    def __ne__(self, other):
        """Not-equality predicate. See __eq__.

        Args:
          other: Another instance of RealAccount.
        Returns:
          A boolean, True if the two real accounts are not equal.
        """
        return not self.__eq__(other)


def iter_children(real_account, leaf_only=False):
    """Iterate this account node and all its children, depth-first.

    Args:
      real_account: An instance of RealAccount.
      leaf_only: A boolean flag, true if we should yield only leaves.
    Yields:
      Instances of RealAccount, beginning with this account. The order is
      undetermined.
    """
    if leaf_only:
        if len(real_account) == 0:
            yield real_account
        else:
            for key, real_child in sorted(real_account.items()):
                for real_subchild in iter_children(real_child, leaf_only):
                    yield real_subchild
    else:
        yield real_account
        for key, real_child in sorted(real_account.items()):
            for real_subchild in iter_children(real_child):
                yield real_subchild


def get(real_account, account_name, default=None):
    """Fetch the subaccount name from the real_account node.

    Args:
      real_account: An instance of RealAccount, the parent node to look for
        children of.
      account_name: A string, the name of a possibly indirect child leaf
        found down the tree of 'real_account' nodes.
      default: The default value that should be returned if the child
        subaccount is not found.
    Returns:
      A RealAccount instance for the child, or the default value, if the child
      is not found.
    """
    if not isinstance(account_name, str):
        raise ValueError
    components = account_name.split(account.sep)
    for component in components:
        real_child = real_account.get(component, default)
        if real_child is default:
            return default
        real_account = real_child
    return real_account


def get_or_create(real_account, account_name):
    """Fetch the subaccount name from the real_account node.

    Args:
      real_account: An instance of RealAccount, the parent node to look for
        children of, or create under.
      account_name: A string, the name of the direct or indirect child leaf
        to get or create.
    Returns:
      A RealAccount instance for the child, or the default value, if the child
      is not found.
    """
    if not isinstance(account_name, str):
        raise ValueError
    components = account_name.split(account.sep)
    path = []
    for component in components:
        path.append(component)
        real_child = real_account.get(component, None)
        if real_child is None:
            real_child = RealAccount(account.join(*path))
            real_account[component] = real_child
        real_account = real_child
    return real_account


def contains(real_account, account_name):
    """True if the given account node contains the subaccount name.

    Args:
      account_name: A string, the name of a direct or indirect subaccount of
        this node.
    Returns:
      A boolean, true the name is a child of this node.
    """
    return get(real_account, account_name) is not None


def realize(entries, min_accounts=None):
    """Group entries by account, into a "tree" of realized accounts. RealAccount's
    are essentially containers for lists of postings and the final balance of
    each account, and may be non-leaf accounts (used strictly for organizing
    accounts into a hierarchy). This is then used to issue reports.

    The lists of postings in each account my be any of the entry types, except
    for Transaction, whereby Transaction entries are replaced by the specific
    Posting legs that belong to the account. Here's a simple diagram that
    summarizes this seemingly complex, but rather simple data structure:

       +-------------+ postings  +------+
       | RealAccount |---------->| Open |
       +-------------+           +------+
                                     |
                                     v
                                +---------+     +-------------+
                                | Posting |---->| Transaction |
                                +---------+     +-------------+
                                     |                         \
                                     v                       +---------+
                                  +-----+                    | Posting |
                                  | Pad |                    +---------+
                                  +-----+
                                     |
                                     v
                                +---------+
                                | Balance |
                                +---------+
                                     |
                                     v
                                 +-------+
                                 | Close |
                                 +-------+
                                     |
                                     .

    Args:
      entries: A list of directives.
    Returns:
      The root RealAccount instance.
    """
    # Create lists of the entries by account.
    postings_map = group_by_account(entries)

    # Create a RealAccount tree and compute the balance for each.
    real_root = RealAccount('')
    for account_name, postings in postings_map.items():
        real_account = get_or_create(real_root, account_name)
        real_account.postings = postings
        real_account.balance = compute_postings_balance(postings)

    # Ensure a minimum set of accounts that should exist. This is typically
    # called with an instance of AccountTypes to make sure that those exist.
    if min_accounts:
        for account_name in min_accounts:
            get_or_create(real_root, account_name)

    return real_root


def group_by_account(entries):
    """Create lists of postings and balances by account.

    This routine aggregates postings and entries grouping them by account name.
    The resulting lists contain postings in-lieu of Transaction directives, but
    the other directives are stored as entries. This yields a list of postings
    or other entries by account. All references to accounts are taken into
    account.

    Args:
      entries: A list of directives.
    Returns:
       A mapping of account name to list of postings, sorted in the same order
       as the entries.
    """
    postings_map = collections.defaultdict(list)
    for entry in entries:

        if isinstance(entry, Transaction):
            # Insert an entry for each of the postings.
            for posting in entry.postings:
                postings_map[posting.account].append(posting)

        elif isinstance(entry, (Open, Close, Balance, Note, Document)):
            # Append some other entries in the realized list.
            postings_map[entry.account].append(entry)

        elif isinstance(entry, Pad):
            # Insert the pad entry in both realized accounts.
            postings_map[entry.account].append(entry)
            postings_map[entry.account_pad].append(entry)

    return postings_map


def compute_postings_balance(postings):
    """Compute the balance of a list of Postings's positions.

    Args:
      postings: A list of Posting instances and other directives (which are
        skipped).
    Returns:
      An Inventory.
    """
    balance = inventory.Inventory()
    for posting in postings:
        if isinstance(posting, data.Posting):
            balance.add_position(posting.position, allow_negative=True)
    return balance


def filter(real_account, predicate):
    """Filter a RealAccount tree of nodes by the predicate.

    This function visits the tree and applies the predicate on each node. It
    returns a partial clone of RealAccount whereby on each node
    - either the predicate is true, or
    - for at least one child of the node the predicate is true.
    All the leaves have the predicate be true.

    Args:
      real_account: An instance of RealAccount.
      predicate: A callable/function which accepts a real_account and returns
        a boolean. If the function returns True, the node is kept.
    Returns:
      A shallow clone of RealAccount is always returned.
    """
    assert isinstance(real_account, RealAccount)

    real_copy = RealAccount(real_account.account)
    real_copy.balance = real_account.balance
    real_copy.postings = real_account.postings

    for child_name, real_child in real_account.items():
        real_child_copy = filter(real_child, predicate)
        if real_child_copy is not None:
            real_copy[child_name] = real_child_copy

    if len(real_copy) > 0 or predicate(real_account):
        return real_copy


def get_postings(real_account):
    """Return a sorted list a RealAccount's postings and children.

    Args:
      real_account: An instance of RealAccount.
    Returns:
      A list of Posting or directories.
    """
    accumulator = []
    for real_child in iter_children(real_account):
        accumulator.extend(real_child.postings)
    accumulator.sort(key=data.posting_sortkey)
    return accumulator


def iterate_with_balance(postings_or_entries):
    """Iterate over the entries, accumulating the running balance.

    For each entry, this yields tuples of the form:

      (entry, postings, change, balance)

    entry: This is the directive for this line. If the list contained Posting
      instance, this yields the corresponding Transaction object.
    postings: A list of postings on this entry that affect the balance. Only the
      postings encountered in the input list are included; only those affect the
      balance. If 'entry' is not a Transaction directive, this should always be
      an empty list. We preserve the original ordering of the postings as they
      appear in the input list.
    change: An Inventory object that reflects the total change due to the
      postings from this entry that appear in the list. For example, if a
      Transaction has three postings and two are in the input list, the sum of
      the two postings will be in the 'change' Inventory object. However, the
      position for the transactions' third posting--the one not included in the
      input list--will not be in this inventory.
    balance: An Inventory object that reflects the balance *after* adding the
      'change' inventory due to this entry's transaction. The 'balance' yielded
      is never None, even for entries that do not affect the balance, that is,
      with an empty 'change' inventory. It's up to the caller, the one rendering
      the entry, to decide whether to render this entry's change for a
      particular entry type.

    Note that if the input list of postings_or_entries is not in sorted date
    order, two postings for the same entry appearing twice with a different date
    in between will cause the entry appear twice. This is correct behavior, and
    it is expected that in practice this should never happen anyway, because the
    list of postings or entries should always be sorted. This method attempts to
    detect this and raises an assertion if this is seen.

    Args:
      postings_or_entries: A list of postings or directive instances.
        Postings affect the balance; other entries do not.
    Yields:
      Tuples of (entry, postings, change, balance) as described above.
    """

    # The running balance.
    balance = inventory.Inventory()

    # Previous date.
    prev_date = None

    # A list of entries at the current date.
    date_entries = []

    first = lambda pair: pair[0]
    for posting_or_entry in postings_or_entries:

        # Get the posting if we are dealing with one.
        if isinstance(posting_or_entry, Posting):
            posting = posting_or_entry
            entry = posting.entry
        else:
            posting = None
            entry = posting_or_entry

        if entry.date != prev_date:
            assert prev_date is None or entry.date > prev_date, (
                "Invalid date order for postings: {} > {}".format(prev_date, entry.date))
            prev_date = entry.date

            # Flush the dated entries.
            for date_entry, date_postings in date_entries:
                change = inventory.Inventory()
                if date_postings:
                    # Compute the change due to this transaction and update the
                    # total balance at the same time.
                    for date_posting in date_postings:
                        change.add_position(date_posting.position, True)
                        balance.add_position(date_posting.position, True)
                yield date_entry, date_postings, change, balance

            date_entries.clear()
            assert not date_entries

        if posting is not None:
            # De-dup multiple postings on the same transaction entry by
            # grouping their positions together.
            index = misc_utils.index_key(date_entries, entry, first, operator.is_)
            if index is None:
                date_entries.append((entry, [posting]))
            else:
                # We are indeed de-duping!
                postings = date_entries[index][1]
                postings.append(posting)
        else:
            # This is a regular entry; nothing to add/remove.
            date_entries.append((entry, []))

    # Flush the final dated entries if any, same as above.
    for date_entry, date_postings in date_entries:
        change = inventory.Inventory()
        if date_postings:
            for date_posting in date_postings:
                change.add_position(date_posting.position, True)
                balance.add_position(date_posting.position, True)
        yield date_entry, date_postings, change, balance
    date_entries.clear()



























# FIXME: Integrate this code with acctree and the rest of the render code.
def dump_tree_balances(real_account, foutput=None):
    """Dump a simple tree of the account balances at cost, for debugging."""

    if foutput is None:
        foutput = sys.stdout

    lines = list(tree_utils.render(
        real_account,
        lambda ra: ra.fullname.split(account.sep)[-1],
        lambda ra: sorted(ra.get_children(), key=lambda x: x.fullname)))
    if not lines:
        return
    width = max(len(line[0] + line[2]) for line in lines)

    for line_first, line_next, account_name, real_account in lines:
        last_entry = real_account.postings[-1] if real_account.postings else None
        balance = getattr(real_account, 'balance', None)
        if not balance.is_empty():
            amounts = balance.get_cost().get_amounts()
            positions = ['{0.number:12,.2f} {0.currency}'.format(amount)
                         for amount in sorted(amounts, key=amount_sortkey)]
        else:
            positions = ['']

        for position, line in zip(positions, chain((line_first + account_name,),
                                                   repeat(line_next))):
            foutput.write('{:{width}}   {:16}\n'.format(line, position, width=width))


# Test:
    # def test_dump_tree_balances(self):
    #     real_root = RealAccount('')
    #     realization.get_or_create(real_root, 'Assets:US:Bank:Checking')
    #     realization.get_or_create(real_root, 'Liabilities:US:CreditCard')

    #     realization.dump_tree_balances(real_root)





# FIXME: TODO, implement these properly.

def reorder_accounts_tree(real_accounts):
    """Reorder the children in a way that is sensible for display.
    We want the most active accounts near the top, and the least
    important ones at the bottom."""

    reorder_accounts_node_by_declaration(real_accounts.get_root())


def reorder_accounts_node_by_declaration(real_account):

    children = []
    for child_account in real_account.children:
        fileloc = reorder_accounts_node_by_declaration(child_account)
        children.append((fileloc, child_account))

    children.sort()
    real_account.children[:] = [x[1] for x in children]

    print(real_account.fullname)
    for fileloc, child in children:
        print('  {:64}  {}'.format(child.name, fileloc))
    print()

    if real_account.postings:
        fileloc = real_account.postings[0].fileloc
    else:
        fileloc = children[0][0]
    return fileloc



def reorder_accounts_node_by_date(real_account):

    children = []
    for child_account in real_account.children:
        reorder_accounts_node_by_date(child_account)
        children.append((child_date, child_account))
    children.sort(reverse=True)

    real_account.children[:] = [x[1] for x in children]

    last_date = children[0][0] if children else datetime.date(1970, 1, 1)

    if real_account.postings:
        last_posting = real_account.postings[-1]
        if hasattr(last_posting, 'date'):
            date = last_posting.date
        else:
            date = last_posting.entry.date

        if date > last_date:
            last_date = date

    return last_date


# FIXME: This file is being cleaned up. Don't worry about all the FIXMEs [2014-02-26]
