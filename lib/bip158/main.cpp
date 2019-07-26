#include <iostream>
#include "blockfilter.h"

int main()
{
    srand(time(NULL));
    for(int loop=0;loop<10;loop++)
    {
        GCSFilter::ElementSet elements2;
        for (int i = 0; i < 10000; ++i)
        {
            GCSFilter::Element element(32);
            element[0] = static_cast<unsigned char>(i);
            element[1] = static_cast<unsigned char>(i >> 8);
            elements2.insert(std::move(element));
        }
        GCSFilter filter({0, 0, 20, 1 << 20},
            elements2);

        GCSFilter::ElementSet elements3;

        for (int j=0;j<10;j++)
        {
            int i=rand()%50000;

            GCSFilter::Element element(32);
            element[0] = static_cast<unsigned char>(i);
            element[1] = static_cast<unsigned char>(i >> 8);

            if(filter.Match(element))
                std::cout << "Found " << i << std::endl;
            else
                std::cout << "Not Found " << i << std::endl;
            elements3.insert(std::move(element));
        }
        if(filter.MatchAny(elements3))
            std::cout << loop << " ***** MatchAny returned true" << std::endl;
        else
            std::cout << loop << " ***** MatchAny returned false" << std::endl;
    }
    return 0;
}
