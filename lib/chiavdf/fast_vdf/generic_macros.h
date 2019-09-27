#ifndef ILYA_SHARED_HEADER_GENERIC_MACROS
#define ILYA_SHARED_HEADER_GENERIC_MACROS

/*
#define main(...) \
    main_inner(int argc, char** argv); \
    int main(int argc, char** argv) { \
        try {\
            return main_inner(argc, argv);\
        } catch(const std::exception& e) {\
            std::cerr << "\n\nUncaught exception: " << e.what() << "\n";\
            char *f=0; *f=1;\
        } catch(const std::string& e) {\
            std::cerr << "\n\nUncaught exception: " << e << "\n";\
            char *f=0; *f=1;\
        } catch(const char* e) {\
            std::cerr << "\n\nUncaught exception: " << e << "\n";\
            char *f=0; *f=1;\
        } catch(...) {\
            std::cerr << "\n\nUncaught exception.\n";\
            char *f=0; *f=1;\
        }\
    }\
    int main_inner(int argc, char** argv)

#ifndef NO_GENERIC_H_ASSERT
    #ifdef assert
        #undef assert
    #endif
    #define assert(v) if (!(v)) { std::cerr << "\n\nAssertion failed: " << __FILE__ << " : " << __LINE__ << "\n"; char* shared_generic_assert_char_123=nullptr; *shared_generic_assert_char_123=1; throw 0; } (void)0
#endif
*/

#endif
