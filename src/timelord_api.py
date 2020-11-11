from typing import Callable

from src.protocols import timelord_protocol
from src.timelord import Timelord
from src.util.api_decorators import api_request


class TimelordAPI:
    timelord: Timelord

    def __init__(self, timelord):
        self.timelord = timelord

    def _set_state_changed_callback(self, callback: Callable):
        pass

    @api_request
    async def challenge_start(self, challenge_start: timelord_protocol.ChallengeStart):
        """
        The full node notifies the timelord node that a new challenge is active, and work
        should be started on it. We add the challenge into the queue if it's worth it to have.
        """
        async with self.timelord.lock:
            if not self.timelord.sanitizer_mode:
                if challenge_start.challenge_hash in self.timelord.seen_discriminants:
                    self.timelord.log.info(
                        f"Have already seen this challenge hash {challenge_start.challenge_hash}. Ignoring."
                    )
                    return
                if challenge_start.weight <= self.timelord.best_weight_three_proofs:
                    self.timelord.log.info(
                        "Not starting challenge, already three proofs at that weight"
                    )
                    return
                self.timelord.seen_discriminants.append(challenge_start.challenge_hash)
                self.timelord.discriminant_queue.append(
                    (challenge_start.challenge_hash, challenge_start.weight)
                )
                self.timelord.log.info("Appended to discriminant queue.")
            else:
                disc_dict = dict(self.timelord.discriminant_queue)
                if challenge_start.challenge_hash in disc_dict:
                    self.timelord.log.info(
                        "Challenge already in discriminant queue. Ignoring."
                    )
                    return
                if challenge_start.challenge_hash in self.timelord.active_discriminants:
                    self.timelord.log.info("Challenge currently running. Ignoring.")
                    return

                self.timelord.discriminant_queue.append(
                    (challenge_start.challenge_hash, challenge_start.weight)
                )
                if challenge_start.weight not in self.timelord.max_known_weights:
                    self.timelord.max_known_weights.append(challenge_start.weight)
                    self.timelord.max_known_weights.sort()
                    if len(self.timelord.max_known_weights) > 5:
                        self.timelord.max_known_weights = (
                            self.timelord.max_known_weights[-5:]
                        )

    @api_request
    async def proof_of_space_info(
        self,
        proof_of_space_info: timelord_protocol.ProofOfSpaceInfo,
    ):
        """
        Notification from full node about a new proof of space for a challenge. If we already
        have a process for this challenge, we should communicate to the process to tell it how
        many iterations to run for.
        """
        async with self.timelord.lock:
            if not self.timelord.sanitizer_mode:
                self.timelord.log.info(
                    f"proof_of_space_info {proof_of_space_info.challenge_hash} {proof_of_space_info.iterations_needed}"
                )
                if (
                    proof_of_space_info.challenge_hash
                    in self.timelord.done_discriminants
                ):
                    self.timelord.log.info(
                        f"proof_of_space_info {proof_of_space_info.challenge_hash} already done, returning"
                    )
                    return
            else:
                disc_dict = dict(self.timelord.discriminant_queue)
                if proof_of_space_info.challenge_hash in disc_dict:
                    challenge_weight = disc_dict[proof_of_space_info.challenge_hash]
                    if challenge_weight >= min(self.timelord.max_known_weights):
                        self.timelord.log.info(
                            "Not storing iter, waiting for more block confirmations."
                        )
                        return
                else:
                    self.timelord.log.info("Not storing iter, challenge inactive.")
                    return

            if proof_of_space_info.challenge_hash not in self.timelord.pending_iters:
                self.timelord.pending_iters[proof_of_space_info.challenge_hash] = []
            if proof_of_space_info.challenge_hash not in self.timelord.submitted_iters:
                self.timelord.submitted_iters[proof_of_space_info.challenge_hash] = []

            if (
                proof_of_space_info.iterations_needed
                not in self.timelord.pending_iters[proof_of_space_info.challenge_hash]
                and proof_of_space_info.iterations_needed
                not in self.timelord.submitted_iters[proof_of_space_info.challenge_hash]
            ):
                self.timelord.log.info(
                    f"proof_of_space_info {proof_of_space_info.challenge_hash} adding "
                    f"{proof_of_space_info.iterations_needed} to "
                    f"{self.timelord.pending_iters[proof_of_space_info.challenge_hash]}"
                )
                self.timelord.pending_iters[proof_of_space_info.challenge_hash].append(
                    proof_of_space_info.iterations_needed
                )
