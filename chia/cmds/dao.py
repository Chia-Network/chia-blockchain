from __future__ import annotations

import click

# from chia.cmds.cmds_util import NODE_TYPES
# from chia.cmds.peer_funcs import peer_async

dao1 = "84e0c0eafaa95a34c293f278ac52e45ce537bab5e752a00e6959a13ae103b65a"
dao2 = "0d6ba19b62531ccb0deb8804313eca283c69560f66f1b7b8a2c1592ae8c35c6b"

prop1 = "ca02a7bbd898b4cdf99e60c923abcf116f3cc8224a790f395c36953f207cf09a"
prop2 = "deb0e38ced1e41de6f92e70e80c418d2d356afaaa99e26f5939dbc7d3ef4772a"


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
    print(f"DAO {dao_id} added with name '{dao_name}'")


# ----------------------------------------------------------------------------------------


@dao_cmd.command("create", short_help="Create, manage or show state of DAOs", no_args_is_help=True)
@click.argument("initial_voting_power", type=str, nargs=1, required=True)
@click.argument("attendance_percentage", type=str, nargs=1, required=True)
@click.argument("proposal_lockup_time", type=str, nargs=1, required=True)
def dao_create(initial_voting_power: str, attendance_percentage: str, proposal_lockup_time: str) -> None:
    print(
        f"Creating new DAO with:"
        f"    initial_voting_power={initial_voting_power}"
        f"    attendance_percentage={attendance_percentage}"
        f"    proposal_lockup_time={proposal_lockup_time}"
        f""
    )


# ----------------------------------------------------------------------------------------


@dao_cmd.command("list", short_help="List and summarize state of all DAOs", no_args_is_help=False)
def dao_list() -> None:
    print(f"'Meta DAO'              {dao1}")
    print(f"'Chia Corporate DAO'    {dao2}")


# ----------------------------------------------------------------------------------------


@dao_cmd.command("vote", short_help="Vote on a proposal belonging to a specific DAO", no_args_is_help=True)
@click.argument("dao_id", type=str, nargs=1, required=True)
@click.argument("proposal_id", type=str, nargs=1, required=True)
@click.argument("number_of_votes", type=str, nargs=1, required=True)
def dao_vote(dao_id: str, proposal_id: str, number_of_votes: str) -> None:
    # TDOO: Proposal id like xxxx:yyyy
    print(f"Transaction pending to add {number_of_votes} votes to proposal {proposal_id}")


# ----------------------------------------------------------------------------------------


@dao_cmd.group("proposal", short_help="Create and add a proposal to a DAO", no_args_is_help=True)
def dao_proposal() -> None:
    pass


@dao_proposal.command("create", short_help="Create a new proposal for a certain DAO_ID")
@click.argument("dao_id", type=str, nargs=1, required=True)
def create_proposal(dao_id: str, name: str, puzzle_params: str) -> None:
    print(f"Creating proposal for DAO {dao1} with name '{name}' and puzzle params ...")


@dao_proposal.command("list", short_help="List proposals for a certain DAO")
@click.argument("dao_id", type=str, nargs=1, required=True)
def list_proposals(dao_id: str) -> None:
    print(f"Listing proposals for DAO {dao_id}:")
    print(f"    'Free Lunch'                       {prop1}")
    print(f"    'XCH 10,000 for the Tree lobby'    {prop2}")


# ----------------------------------------------------------------------------------------


# dao_cmd.add_command(dao_)
dao_cmd.add_command(dao_add)
dao_cmd.add_command(dao_create)
dao_cmd.add_command(dao_list)
dao_cmd.add_command(dao_vote)
dao_cmd.add_command(dao_proposal)
