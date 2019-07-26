#include "blockfilter.h"

int main()
{
    GCSFilter::ElementSet elements1;
    for (int i = 0; i < 10000; ++i) {
        GCSFilter::Element element(32);
        element[0] = static_cast<unsigned char>(i);
        element[1] = static_cast<unsigned char>(i >> 8);
        elements1.insert(std::move(element));
    }

    uint64_t siphash_k0 = 0;
    {
        GCSFilter filter({siphash_k0, 0, 20, 1 << 20}, elements1);

        siphash_k0++;
    }
    
    GCSFilter::ElementSet elements2;
    for (int i = 0; i < 10000; ++i) {
        GCSFilter::Element element(32);
        element[0] = static_cast<unsigned char>(i);
        element[1] = static_cast<unsigned char>(i >> 8);
        elements2.insert(std::move(element));
    }
    GCSFilter filter({0, 0, 20, 1 << 20}, elements2);

    {
        filter.Match(GCSFilter::Element());
    }
    return 0;
}

