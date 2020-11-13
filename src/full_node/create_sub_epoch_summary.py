def create_sub_epoch_summary(self):
    prev_sb: Optional[SubBlockRecord] = self.blockchain.sub_blocks.get(block.prev_header_hash, None)
    if block.height == 0:
        ips = self.constants.IPS_STARTING
    else:
        assert prev_sb is not None
        prev_ip_iters = calculate_ip_iters(self.constants, prev_sb.ips, prev_sb.required_iters)
        prev_sp_iters = calculate_sp_iters(self.constants, prev_sb.ips, prev_sb.required_iters)
        ips = get_next_ips(
            self.constants,
            self.blockchain.sub_blocks,
            self.blockchain.height_to_hash,
            block.prev_header_hash,
            prev_sb.height,
            prev_sb.ips,
            prev_sb.deficit,
            len(block.finished_sub_slots) > 0,
            uint128(block.total_iters - prev_ip_iters + prev_sp_iters),
        )
    overflow = is_overflow_sub_block(self.constants, ips, required_iters)
    deficit = calculate_deficit(self.constants, block.height, prev_sb, overflow, len(block.finished_sub_slots) > 0)
    finishes_se = finishes_sub_epoch(
        self.constants, block.height, deficit, False, self.blockchain.sub_blocks, prev_sb.header_hash
    )
    finishes_epoch: bool = finishes_sub_epoch(
        self.constants, block.height, deficit, True, self.blockchain.sub_blocks, prev_sb.header_hash
    )

    if finishes_se:
        assert prev_sb is not None
        if finishes_epoch:
            ip_iters = calculate_ip_iters(self.constants, ips, required_iters)
            sp_iters = calculate_sp_iters(self.constants, ips, required_iters)
            next_difficulty = get_next_difficulty(
                self.constants,
                self.blockchain.sub_blocks,
                self.blockchain.height_to_hash,
                block.header_hash,
                block.height,
                uint64(block.weight - prev_sb.weight),
                deficit,
                True,
                uint128(block.total_iters - ip_iters + sp_iters),
            )
            next_ips = get_next_ips(
                self.constants,
                self.blockchain.sub_blocks,
                self.blockchain.height_to_hash,
                block.header_hash,
                block.height,
                ips,
                deficit,
                True,
                uint128(block.total_iters - ip_iters + sp_iters),
            )
        else:
            next_difficulty = None
            next_ips = None
        ses: Optional[SubEpochSummary] = make_sub_epoch_summary(
            self.constants, self.blockchain.sub_blocks, block.height, prev_sb, next_difficulty, next_ips
        )
    else:
        ses: Optional[SubEpochSummary] = None
