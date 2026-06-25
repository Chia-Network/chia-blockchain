#include "export_compact_vdf.hpp"
#include "process_compact_vdf.hpp"

#include <curl/curl.h>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void print_usage(const char* argv0) {
    std::cerr << "Usage:\n"
              << "  " << argv0
              << " --db <blockchain_v2.sqlite> --compactvdf <compactvdf-file> [--batch-size N] [--threads N] [--dryrun]\n"
              << "  " << argv0
              << " --db <blockchain_v2.sqlite> --remote-compactvdf-url <base-url> [--batch-size N] [--threads N] "
                 "[--dryrun]\n"
              << "  " << argv0
              << " --db <blockchain_v2.sqlite> --export-compactvdf [--export-chunk-size N] [--output-dir DIR]\n"
              << "\n"
              << "Process mode (local file):\n"
              << "  Apply a compactvdf JSON-lines file to a v2 chia blockchain database.\n"
              << "  Validated compact proofs are merged into blocks and written back to full_blocks.\n"
              << "  The compactvdf file is deleted when processing completes successfully.\n"
              << "\n"
              << "Process mode (remote URL):\n"
              << "  Download compactvdf files from a base URL in 10,000-block chunks starting at height 0.\n"
              << "  Files are fetched from {base-url}/compactvdf-{start}to{end} until HTTP 404.\n"
              << "  Each chunk is validated and applied before the next download.\n"
              << "\n"
              << "  --dryrun   Validate and apply proofs in memory only; no database or file writes.\n"
              << "             Uses PRAGMA query_only; stop the full node before running.\n"
              << "\n"
              << "Export mode:\n"
              << "  Scan the main chain from height 0 through the peak and write compactvdf JSON-lines\n"
              << "  files for every --export-chunk-size blocks (default 10000) into --output-dir.\n"
              << "  Files are named compactvdf-<n>to<m> where n and m are the inclusive height range.\n"
              << "  Only VDF proofs with witness_type 0 are exported.\n";
}

struct CurlGlobalInit {
    CurlGlobalInit() {
        if (curl_global_init(CURL_GLOBAL_DEFAULT) != 0) {
            throw std::runtime_error("curl_global_init failed");
        }
    }
    ~CurlGlobalInit() { curl_global_cleanup(); }
};

}  // namespace

int main(int argc, char** argv) {
    try {
        const CurlGlobalInit curl_init;

        ProcessCompactVdfOptions process_options;
        ExportCompactVdfOptions export_options;
        bool export_mode = false;

        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--db" && i + 1 < argc) {
                process_options.db_path = argv[++i];
                export_options.db_path = process_options.db_path;
            } else if (arg == "--compactvdf" && i + 1 < argc) {
                process_options.compact_vdf_path = argv[++i];
            } else if (arg == "--remote-compactvdf-url" && i + 1 < argc) {
                process_options.remote_compact_vdf_base_url = argv[++i];
            } else if (arg == "--batch-size" && i + 1 < argc) {
                process_options.batch_size = static_cast<std::size_t>(std::stoul(argv[++i]));
            } else if (arg == "--threads" && i + 1 < argc) {
                process_options.thread_count = static_cast<unsigned>(std::stoul(argv[++i]));
            } else if (arg == "--dryrun") {
                process_options.dry_run = true;
            } else if (arg == "--export-compactvdf") {
                export_mode = true;
            } else if (arg == "--export-chunk-size" && i + 1 < argc) {
                export_options.chunk_size = static_cast<std::size_t>(std::stoul(argv[++i]));
            } else if (arg == "--output-dir" && i + 1 < argc) {
                export_options.output_dir = argv[++i];
            } else if (arg == "--help" || arg == "-h") {
                print_usage(argv[0]);
                return 0;
            } else {
                std::cerr << "Unknown argument: " << arg << '\n';
                print_usage(argv[0]);
                return 1;
            }
        }

        if (export_options.db_path.empty()) {
            print_usage(argv[0]);
            return 1;
        }

        if (export_mode) {
            export_compact_vdf_files(export_options);
            return 0;
        }

        const bool has_local = !process_options.compact_vdf_path.empty();
        const bool has_remote = !process_options.remote_compact_vdf_base_url.empty();
        if (has_local == has_remote) {
            std::cerr << "Specify exactly one of --compactvdf or --remote-compactvdf-url\n";
            print_usage(argv[0]);
            return 1;
        }

        if (has_remote) {
            process_compact_vdf_remote(process_options);
        } else {
            process_compact_vdf_file(process_options);
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << '\n';
        return 1;
    }
}
