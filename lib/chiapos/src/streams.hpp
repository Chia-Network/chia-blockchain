// Copyright 2018 Chia Network Inc

// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at

//    http://www.apache.org/licenses/LICENSE-2.0

// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#ifndef SRC_CPP_STREAMS_HPP_
#define SRC_CPP_STREAMS_HPP_

class StreamBase {
  public:
    void CheckError(const std::ios* stream) {
        if (!stream->good()) {
            if (stream->bad()) {
                perror("Error: badbit detected");
                error = true;
            } else if (stream->fail()) {
                if (stream->eof()) {
                    std::cout << "Error: Can't read the desired characters as EOF was reached.\n";
                } else {
                    std::cout << "Error: failbit detected. Logical error on i/o operation.\n";
                }
                error = true;
            }
        }
    }
  protected:
    bool error = false;
};

class StreamReader : StreamBase {
  public:
    StreamReader(std::string& filename) {
        reader = new std::ifstream(filename, std::fstream::in | std::fstream::binary);
        if (!reader->is_open()) {
            perror("Error while opeining the file");
            throw std::string("Error while opening the file");
        }
    }

    void seekg(uint64_t byte) {
        reader->seekg(byte);
    }

    void read(char* buffer, int size) {
        reader->read(buffer, size);
        CheckError(reader);
        if (error) {
            throw std::string("ifsteram error detected.");
        }
    }

    void close() {
        reader->close();
    }

    ~StreamReader() {
        delete(reader);
    }
  private:
    std::ifstream* reader;
};

class StreamWriter : StreamBase {
  public:
    StreamWriter(std::string& filename) {
        writer = new std::ofstream(filename, std::fstream::in | std::fstream::out | std::fstream::binary);
        if (!writer->is_open()) {
            perror("Error while opeining the file");
            throw std::string("Error while opening the file");
        }
    }

    void seekp(uint64_t byte) {
        writer->seekp(byte);
    }

    void close() {
        writer->close();
    }

    void write(const char* buffer, int size) {
        writer->write(buffer, size);
        CheckError(writer);
        if (error) {
            throw std::string("ofstream error detected.");
        }
    }

    void flush() {
        writer->flush();
    }

    ~StreamWriter() {
        delete(writer);
    }
  private:
    std::ofstream* writer;
};

#endif  // SRC_CPP_STREAMS_HPP_
