#include <boost/asio.hpp>
#include "vdf.h"
using boost::asio::ip::tcp;

const int max_length = 2048;
const int kMaxProcessesAllowed = 3;
std::mutex socket_mutex;

void PrintInfo(std::string input) {
    print("VDF Server: " + input);
}

void CreateAndWriteProof(integer D, form x, int64_t num_iterations, WesolowskiCallback& weso, bool& stop_signal, tcp::socket& sock) {
    Proof result = CreateProofOfTimeNWesolowski(D, x, num_iterations, 0, weso, 2, 0, stop_signal);
    if (stop_signal == true) {
        PrintInfo("Got stop signal before completing the proof!");
        return ;
    }
    // Writes the number of iterations
    std::vector<unsigned char> bytes = ConvertIntegerToBytes(integer(num_iterations), 8);

    // Writes the y, with prepended size
    std::vector<unsigned char> y_size = ConvertIntegerToBytes(integer(result.y.size()), 8);
    bytes.insert(bytes.end(), y_size.begin(), y_size.end());
    bytes.insert(bytes.end(), result.y.begin(), result.y.end());

    // Writes the proof, with prepended size
    std::vector<unsigned char> proof_size = ConvertIntegerToBytes(integer(result.proof.size()), 8);
    bytes.insert(bytes.end(), proof_size.begin(), proof_size.end());
    bytes.insert(bytes.end(), result.proof.begin(), result.proof.end());

    std::string str_result = "WESO" + BytesToStr(bytes);
    std::lock_guard<std::mutex> lock(socket_mutex);
    PrintInfo("Generated proof = " + str_result);;
    // Write "WESO" marker
    // boost::asio::write(sock, boost::asio::buffer("WESO", 4));
    boost::asio::write(sock, boost::asio::buffer(str_result.c_str(), str_result.size()));
}

void session(tcp::socket sock) {
    try {
        char disc[350];
        char disc_size[5];
        boost::system::error_code error;

        memset(disc,0x00,sizeof(disc)); // For null termination
        memset(disc_size,0x00,sizeof(disc_size)); // For null termination

        boost::asio::read(sock, boost::asio::buffer(disc_size, 3), error);
        int disc_int_size = atoi(disc_size);

        boost::asio::read(sock, boost::asio::buffer(disc, disc_int_size), error);

        integer D(disc);
        PrintInfo("Discriminant = " + to_string(D.impl));

        int space_needed = kSwitchIters / 10 + (kMaxItersAllowed - kSwitchIters) / 100;
        forms = (form*) calloc(space_needed, sizeof(form));

        PrintInfo("Calloc'd " + to_string(space_needed * sizeof(form)) + " bytes");

        // Init VDF the discriminant...

        if (error == boost::asio::error::eof)
            return ; // Connection closed cleanly by peer.
        else if (error)
            throw boost::system::system_error(error); // Some other error.

        if (getenv( "warn_on_corruption_in_production" )!=nullptr) {
            warn_on_corruption_in_production=true;
        }
        if (is_vdf_test) {
            PrintInfo( "=== Test mode ===" );
        }
        if (warn_on_corruption_in_production) {
            PrintInfo( "=== Warn on corruption enabled ===" );
        }
        assert(is_vdf_test); //assertions should be disabled in VDF_MODE==0
        init_gmp();
        allow_integer_constructor=true; //make sure the old gmp allocator isn't used
        set_rounding_mode();

        integer L=root(-D, 4);
        form f=form::generator(D);

        bool stop_signal = false;
        // (iteration, thread_id)
        std::set<std::pair<uint64_t, uint64_t> > seen_iterations;
        bool stop_vector[100];

        std::vector<std::thread> threads;
        WesolowskiCallback weso(1000000);

        //mpz_init(weso.forms[0].a.impl);
        //mpz_init(weso.forms[0].b.impl);
        //mpz_init(weso.forms[0].c.impl);

        forms[0]=f;
        weso.D = D;
        weso.L = L;
        weso.kl = 10;

        bool stopped = false;
        bool got_iters = false;
        std::thread vdf_worker(repeated_square, f, D, L, std::ref(weso), std::ref(stopped));

        // Tell client that I'm ready to get the challenges.
        boost::asio::write(sock, boost::asio::buffer("OK", 2));
        char data[20];

        while (!stopped) {
            memset(data, 0, sizeof(data));
            boost::asio::read(sock, boost::asio::buffer(data, 2), error);
            int size = (data[0] - '0') * 10 + (data[1] - '0');
            memset(data, 0, sizeof(data));
            boost::asio::read(sock, boost::asio::buffer(data, size), error);
            int iters = atoi(data);
            got_iters = true;

            if (iters == 0) {
                PrintInfo("Got stop signal!");
                stopped = true;
                for (int i = 0; i < threads.size(); i++)
                    stop_vector[i] = true;
                for (int t = 0; t < threads.size(); t++) {
                    threads[t].join();
                }
                vdf_worker.join();
                free(forms);
            } else {
                int max_iter = 0;
                int max_iter_thread_id = -1;
                int min_iter = std::numeric_limits<int> :: max();
                bool unique = true;
                for (auto active_iter: seen_iterations) {
                    if (active_iter.first > max_iter) {
                        max_iter = active_iter.first;
                        max_iter_thread_id = active_iter.second;
                    }
                    if (active_iter.first < min_iter) {
                        min_iter = active_iter.first;
                    }
                    if (active_iter.first == iters) {
                        unique = false;
                        break;
                    }
                }
                if (!unique) {
                    PrintInfo("Duplicate iteration " + to_string(iters) + "... Ignoring.");
                    continue;
                }
                if (threads.size() < kMaxProcessesAllowed || iters < min_iter) {
                    seen_iterations.insert({iters, threads.size()});
                    PrintInfo("Running proving for iter: " + to_string(iters));
                    stop_vector[threads.size()] = false;
                    threads.push_back(std::thread(CreateAndWriteProof, D, f, iters, std::ref(weso),
                                      std::ref(stop_vector[threads.size()]), std::ref(sock)));
                    if (threads.size() > kMaxProcessesAllowed) {
                        PrintInfo("Stopping proving for iter: " + to_string(max_iter));
                        stop_vector[max_iter_thread_id] = true;
                        seen_iterations.erase({max_iter, max_iter_thread_id});
                    }
                }
            }
        }
    } catch (std::exception& e) {
        PrintInfo("Exception in thread: " + to_string(e.what()));
    }

    try {
        // Tell client I've stopped everything, wait for ACK and close.
        boost::system::error_code error;

        PrintInfo("Stopped everything! Ready for the next challenge.");

        std::lock_guard<std::mutex> lock(socket_mutex);
        boost::asio::write(sock, boost::asio::buffer("STOP", 4));

        char ack[5];
        memset(ack,0x00,sizeof(ack));
        boost::asio::read(sock, boost::asio::buffer(ack, 3), error);
        assert (strncmp(ack, "ACK", 3) == 0);
    } catch (std::exception& e) {
        PrintInfo("Exception in thread: " + to_string(e.what()));
    }
}

void server(boost::asio::io_context& io_context, unsigned short port)
{
  tcp::acceptor a(io_context, tcp::endpoint(tcp::v4(), port));
  std::thread t(session, a.accept());
  t.join();
}

int main(int argc, char* argv[])
{
  try
  {
    if (argc != 2)
    {
      PrintInfo("Usage: blocking_tcp_echo_server <port>");
      return 1;
    }

    boost::asio::io_context io_context;

    server(io_context, std::atoi(argv[1]));
  }
  catch (std::exception& e)
  {
    PrintInfo("Exception: " + to_string(e.what()));
  }

  return 0;
}
