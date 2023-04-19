from __future__ import annotations

import json
from typing import Any, Optional

import click

from chia.util.hash import std_hash

dao1 = "84e0c0eafaa95a34c293f278ac52e45ce537bab5e752a00e6959a13ae103b65a"
dao2 = "0d6ba19b62531ccb0deb8804313eca283c69560f66f1b7b8a2c1592ae8c35c6b"

prop1 = "ca02a7bbd898b4cdf99e60c923abcf116f3cc8224a790f395c36953f207cf09a"
prop2 = "deb0e38ced1e41de6f92e70e80c418d2d356afaaa99e26f5939dbc7d3ef4772a"


def set(var: str, val: Any) -> None:
    with open("state.json", "r") as f:
        state = json.load(f)
    state[var] = val
    with open("state.json", "w") as f:
        json.dump(state, f)


def get(var: str) -> Optional[Any]:
    with open("state.json", "r") as f:
        state = json.load(f)
    if var in state:
        return state[var]
    return None


def remove(var: str) -> None:
    with open("state.json", "r") as f:
        state = json.load(f)
    del state[var]
    with open("state.json", "w") as f:
        json.dump(state, f)


def add_dao(dao_id: str, dao_name: str) -> None:
    daos = get("daos")
    if daos is None:
        daos = []
    daos.append({"dao_id": dao_id, "dao_name": dao_name})
    set("daos", daos)


def add_proposal(prop_id: str, prop_name: str, type: str) -> None:
    proposals = get("proposals")
    if proposals is None:
        proposals = []
    proposals.append({"prop_id": prop_id, "prop_name": prop_name, "type": type})
    set("proposals", proposals)


@click.group("dao", short_help="Create, manage or show state of DAOs", no_args_is_help=True)
@click.pass_context
def dao_cmd(
    ctx: click.Context,
    # rpc_port: Optional[int],
    # connections: bool,
    # add_connection: str,
    # remove_connection: str,
    # node_type: str,
) -> None:
    print("")
    # asyncio.run(
    #     dao_async(
    #         node_type,
    #         rpc_port,
    #         ctx.obj["root_path"],
    #         connections,
    #         add_connection,
    #         remove_connection,
    #     )
    # )


# voting_power
# attendance_percentage
# proposal_lockup_time


# @dao_cmd.group("", short_help="", no_args_is_help=True)
# def dao_() -> None:
#     pass

# ----------------------------------------------------------------------------------------


@dao_cmd.command("add", short_help="Make your Chia client aware of a new DAO", no_args_is_help=True)
@click.argument("dao_id", type=str, nargs=1, required=True)
@click.argument("dao_name", type=str, nargs=1, required=False, default="")
def dao_add(dao_id: str, dao_name: str) -> None:
    print(f"Adding DAO {dao_id} with name '{dao_name}'")
    add_dao(dao_id, dao_name)


# ----------------------------------------------------------------------------------------


@dao_cmd.command("create", short_help="Create, manage or show state of DAOs", no_args_is_help=True)
@click.argument("initial_voting_power", type=str, nargs=1, required=True)
@click.argument("attendance_percentage", type=str, nargs=1, required=True)
@click.argument("proposal_lockup_time", type=str, nargs=1, required=True)
@click.argument("dao_name", type=str, nargs=1, required=True)
def dao_create(initial_voting_power: str, attendance_percentage: str, proposal_lockup_time: str, dao_name: str) -> None:
    print(
        f"Creating new DAO '{dao_name}' with:"
        f"    initial_voting_power={initial_voting_power}"
        f"    attendance_percentage={attendance_percentage}"
        f"    proposal_lockup_time={proposal_lockup_time}"
        f"Note that this name is stored only locally."
    )
    # asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, send))
    dao_id = std_hash(f"{initial_voting_power} {attendance_percentage} {proposal_lockup_time}")
    add_dao(str(dao_id), dao_name)


# ----------------------------------------------------------------------------------------


@dao_cmd.command("list", short_help="List and summarize state of all DAOs known to us", no_args_is_help=False)
def dao_list() -> None:
    # print(f"'Meta DAO'              {dao1}")
    # print(f"'Chia Corporate DAO'    {dao2}")
    daos = get("daos")
    if daos is None:
        print("No known DAOs")
        return
    print(f"{' '*25} DAO ID {' '*25}         Votes  Name")
    for dao in daos:
        print(f"{dao['dao_id']}   1000   '{dao['dao_name']}' ")


# ----------------------------------------------------------------------------------------


@dao_cmd.command("vote", short_help="Vote on a proposal belonging to a specific DAO", no_args_is_help=True)
@click.argument("dao_id", type=str, nargs=1, required=True)
@click.argument("proposal_id", type=str, nargs=1, required=True)
@click.argument("number_of_votes", type=str, nargs=1, required=True)
def dao_vote(dao_id: str, proposal_id: str, number_of_votes: str) -> None:
    # TODO: Proposal id like xxxx:yyyy
    print(f"Transaction pending to add {number_of_votes} votes to proposal {proposal_id}")


# ----------------------------------------------------------------------------------------


@dao_cmd.group("proposal", short_help="Create and add a proposal to a DAO", no_args_is_help=True)
def dao_proposal() -> None:
    pass


# TODO: Do we need a way to manually add proposals? They should be picked up via hints


@dao_proposal.command("create", short_help="Create a new proposal for a certain DAO_ID")
@click.argument("dao_id", type=str, nargs=1, required=True)
@click.argument("prop_name", type=str, nargs=1, required=True)
@click.argument("spend_amount", type=int, nargs=1, required=True)
@click.argument("address", type=str, nargs=1, required=True)
@click.argument("proposal_lockup_time", type=int, nargs=1, required=True)
def create_proposal(dao_id: str, prop_name: str, spend_amount: int, address: str, proposal_lockup_time: int) -> None:
    """Proposal Spend creation. Types:
    - S: Spend   Spend some of the Treasury's assets
    - U: Update  Update Treasury parameters
    """
    print(f"Creating proposal '{prop_name}' for DAO {dao_id} with name to spend {spend_amount} to {address} ...")
    # TODO: print(closing on {date})
    type = "SPEND"
    prop_id = std_hash(f"{type} {spend_amount} {address} {proposal_lockup_time}")
    add_proposal(str(prop_id), prop_name, type)


@dao_proposal.command("list", short_help="List proposals for a certain DAO")
@click.argument("dao_id", type=str, nargs=1, required=True)
def list_proposals(dao_id: str) -> None:
    print(f"Listing proposals for DAO {dao_id} with 1000 total possible votes:")
    # print(f"    'Free Lunch'                       {prop1}")
    # print(f"    'XCH 10,000 for the Tree lobby'    {prop2}")
    ps = get("proposals")
    if ps is None:
        print("    No Proposals")
        return

    print(f"{' '*25} Proposal ID {' '*25}       TYPE FOR AGAINST Name")
    for p in ps:
        print(f"{p['prop_id']}   {p['type']} 10%  15%   '{p['prop_name']}' ")


# ----------------------------------------------------------------------------------------


@dao_proposal.command("mint", short_help="Create more voting tokens (CATs) for this DAO")
@click.argument("dao_id", type=str, nargs=1, required=True)
@click.argument("amount", type=str, nargs=1, required=True)
def dao_mint_voting_tokens(dao_id: str, name: str, puzzle_params: str) -> None:
    """
    Create a proposal of type "D" to mint more voting tokens.
       - D: Dangerous  This proposal type may attempt to both modify the
                       Treasury rules, AND spend money from the Treasury.
                       USE CAUTION.

       No tokens are created unless and until this proposal passes.
    """
    print(f"Creating proposal for DAO {dao1} with name '{name}' and puzzle params ...")


# ----------------------------------------------------------------------------------------

# dao_cmd.add_command(dao_)
dao_cmd.add_command(dao_add)
dao_cmd.add_command(dao_create)
dao_cmd.add_command(dao_list)
dao_cmd.add_command(dao_vote)
dao_cmd.add_command(dao_proposal)


# TODO: status: how many of your voting coins are locked away vs. spendable, etc.
