bip158 : main.o script.o strencodings.o uint256.o transaction.o threadnames.o fs.o cleanse.o lockedpool.o logging.o blockfilter.o siphash.o bytevectorhash.o random.o sha256.o sha512.o chacha20.o block.o time.o
	g++ -o bip158 main.o script.o strencodings.o uint256.o transaction.o threadnames.o fs.o cleanse.o logging.o lockedpool.o blockfilter.o siphash.o bytevectorhash.o random.o sha256.o sha512.o chacha20.o block.o time.o -lboost_system -lpthread -lboost_thread -lboost_filesystem -lssl -lcrypto

main.o : main.cpp
	g++ -I. -std=c++14 -c main.cpp
blockfilter.o : blockfilter.cpp 
	g++ -I. -std=c++14 -c blockfilter.cpp 
siphash.o : crypto/siphash.cpp
	g++ -I. -std=c++14 -c crypto/siphash.cpp
bytevectorhash.o : util/bytevectorhash.cpp 
	g++ -I. -std=c++14 -c util/bytevectorhash.cpp
random.o : random.cpp
	g++ -I. -std=c++14 -c random.cpp
sha256.o : crypto/sha256.cpp
	g++ -I. -std=c++14 -c crypto/sha256.cpp
sha512.o : crypto/sha512.cpp
	g++ -I. -std=c++14 -c crypto/sha512.cpp
chacha20.o : crypto/chacha20.cpp 
	g++ -I. -std=c++14 -c crypto/chacha20.cpp 
block.o : primitives/block.cpp
	g++ -I. -std=c++14 -c primitives/block.cpp
time.o : util/time.cpp
	g++ -DHAVE_WORKING_BOOST_SLEEP -I. -std=c++14 -c util/time.cpp
cleanse.o : support/cleanse.cpp
	g++ -I. -std=c++14 -c support/cleanse.cpp
lockedpool.o : support/lockedpool.cpp
	g++ -I. -std=c++14 -c support/lockedpool.cpp
logging.o : logging.cpp
	g++ -I. -std=c++14 -c logging.cpp
fs.o : fs.cpp
	g++ -I. -std=c++14 -c fs.cpp
threadnames.o : util/threadnames.cpp
	g++ -I. -std=c++14 -c util/threadnames.cpp
transaction.o : primitives/transaction.cpp
	g++ -I. -std=c++14 -c primitives/transaction.cpp
uint256.o : uint256.cpp
	g++ -I. -std=c++14 -c uint256.cpp
strencodings.o : util/strencodings.cpp
	g++ -I. -std=c++14 -c util/strencodings.cpp
script.o : script/script.cpp
	g++ -I. -std=c++14 -c script/script.cpp
clean :
	rm bip158 main.o script.o strencodings.o uint256.o transaction.o threadnames.o fs.o cleanse.o logging.o lockedpool.o blockfilter.o siphash.o bytevectorhash.o random.o sha256.o sha512.o chacha20.o block.o time.o
