"""
Sanity checks.
(Note that these don't have anything to do with 'Check' directives.
"""
from os import path
from collections import namedtuple, defaultdict

from beancount.core.account import Account
from beancount.core.data import Open, Close, Check, Transaction, Document
from beancount.core import data
from beancount.core import getters
from beancount import utils


# An error from one of the checks.
ValidationError = namedtuple('ValidationError', 'fileloc message entry')


def validate_open_close(entries, accounts):
    """Some entries may not be present more than once for each account or date.
    Open and Close are unique per account, for instance. Check is unique
    for each date. There are more. Return a list of errors on non-unique
    entries.
    """

    open_map = {}
    close_map = {}
    check_errors = []

    def check_one(entry, account):
        """Check a single entry."""
        open = open_map.get(account)
        if open is None or entry.date < open.date:
            check_errors.append(ValidationError(entry.fileloc,
                                                "Unknown account {} (or perhaps wrong date?).".format(account.name),
                                                entry))

        close = close_map.get(account)
        if close is not None and entry.date > close.date:
            check_errors.append(ValidationError(entry.fileloc,
                                                "Entry after account {} closed.".format(account.name),
                                                entry))

    # Check all entries for missing open directives and references to accounts
    # which haven't been opened.
    for entry in entries:
        if isinstance(entry, Transaction):
            for posting in entry.postings:
                check_one(entry, posting.account)

        elif isinstance(entry, Open):
            account = entry.account
            if account in open_map:
                check_errors.append(ValidationError(entry.fileloc,
                                                    "Duplicate open entry for {}.".format(account.name),
                                                    entry))
            else:
                open_map[account] = entry

        elif isinstance(entry, Close):
            account = entry.account
            if account in close_map:
                check_errors.append(ValidationError(entry.fileloc,
                                                    "Duplicate close entry for {}.".format(account.name),
                                                    entry))
            else:
                close_map[account] = entry

        elif isinstance(entry, Check):
            if entry.account in accounts:
                # The account is an account with transactions; check the fast
                # path.
                check_one(entry, entry.account)
            else:
                # Parent accounts with subaccounts. Check that there exist at
                # least one sub-account that is currently open for the check,
                # where the check is valid.
                error_entry = None
                for account, open in open_map.items():
                    if not account.name.startswith(entry.account.name):
                        continue
                    if entry.date >= open.date:
                        close = close_map.get(account)
                        if close is None or entry.date <= close.date:
                            error_entry = None
                            break
                        else:
                            error_entry = close
                    else:
                        error_entry = open

                if error_entry:
                    if isinstance(error_entry, Open):
                        check_errors.append(ValidationError(error_entry.fileloc,
                                                            "Unknown account {} (or perhaps wrong date?).".format(error_entry.account.name),
                                                            error_entry))
                    else:
                        assert isinstance(error_entry, Close)
                        check_errors.append(ValidationError(error_entry.fileloc,
                                                            "Entry after account {} closed.".format(error_entry.account.name),
                                                            error_entry))

        elif hasattr(entry, 'account'):
            check_one(entry, entry.account)

    # Check to make sure that all accounts parsed have a corresponding open directive.
    for account in accounts:
        if account not in open_map:
            check_errors.append(ValidationError(data.FileLocation('<validate_open_close>', 0),
                                                "No open directive for account {}.".format(account.name),
                                                None))

    return check_errors, open_map, close_map


def validate_unused_accounts(entries, accounts):
    """Find the list of accounts referred to by non-open entries,
    and check that against the total list of accounts. Accounts which are only
    referred to by open entries are probably unused."""

    # Find all the accounts referenced by entries which are not Open, and the
    # open directives for error reporting below.
    open_map = {}
    referenced_accounts = set()
    for entry in entries:
        if isinstance(entry, Open):
            open_map[entry.account] = entry
            continue
        referenced_accounts.update(utils.get_tuple_typed_values(entry, Account))

    # Unreferenced accounts are unused accounts.
    unused_accounts = set(accounts) - referenced_accounts

    # Create a list of suitable errors, with the location of the spurious Open
    # directives.
    return [ValidationError(open_map[account].fileloc,
                            "Unused account {}.".format(account.name),
                            open_map[account])
            for account in unused_accounts]


def validate_currency_constraints(entries):
    """Check that each account has currencies within its declared constraints."""

    open_map = {entry.account: entry
                for entry in utils.filter_type(entries, Open)}

    errors = []
    for entry in utils.filter_type(entries, Transaction):
        for posting in entry.postings:
            try:
                open_entry = open_map[posting.account]
                valid_currencies = open_entry.currencies
            except KeyError:
                valid_currencies = []
            
            if not valid_currencies:
                continue
            if posting.position.lot.currency not in valid_currencies:
                errors.append(ValidationError(
                    entry.fileloc,
                    "Invalid currency {} for account '{}'.".format(
                        posting.position.lot.currency, posting.account.name),
                    entry))

    return errors


def validate_documents_paths(entries):
    """Check that all filenames in Document entries are absolute filenames."""

    return [ValidationError(entry.fileloc, "Invalid relative path for entry.", entry)
            for entry in utils.filter_type(entries, Document)
            if not path.isabs(entry.filename)]


def validate(entries):
    """Perform all the standard checks on parsed contents."""

    accounts = getters.get_accounts(entries).values()

    # Check for unused accounts.
    unused_errors = validate_unused_accounts(entries, accounts)

    # Validate open/close directives and accounts referred outside of those.
    check_errors, _, _ = validate_open_close(entries, accounts)

    # Check the currency constraints.
    constraint_errors = validate_currency_constraints(entries)

    # Sanity checks for documents.
    doc_errors = validate_documents_paths(entries)

    return (unused_errors + check_errors + constraint_errors + doc_errors)
