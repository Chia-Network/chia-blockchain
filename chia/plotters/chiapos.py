from chiapos import DiskPlotter


def plot_chia(args):
    try:
        plotter = DiskPlotter()
        plotter.create_plot_disk(
            args.tmpdir,
            args.tmpdir2,
            args.finaldir,
            args.filename,
            args.size,
            args.memo,
            args.id,
            args.buffer,
            args.buckets,
            args.stripes,
            args.threads,
            args.nobitfield,
        )
    except Exception as e:
        print(f"Exception while plotting: {e}")
