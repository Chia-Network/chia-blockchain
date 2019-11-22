/* 
 *
 * The MIT License (MIT)
 * 
 * Copyright (c) 2015 Charles Salvia
 * 
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 * 
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 * 
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
*/

#include <functional>
#include <memory>
#include <iostream>
#include <vector>

using namespace std;

#ifndef INCLUDE_STACK_ALLOCATOR_HPP
#define INCLUDE_STACK_ALLOCATOR_HPP



template <class T, std::size_t N, class Allocator = std::allocator<T>>
class stack_allocator
{
	public:

	typedef typename std::allocator_traits<Allocator>::value_type value_type;
	typedef typename std::allocator_traits<Allocator>::pointer pointer;
	typedef typename std::allocator_traits<Allocator>::const_pointer const_pointer;
	typedef typename Allocator::reference reference;
	typedef typename Allocator::const_reference const_reference;
	typedef typename std::allocator_traits<Allocator>::size_type size_type;
	typedef typename std::allocator_traits<Allocator>::difference_type difference_type;

	typedef typename std::allocator_traits<Allocator>::const_void_pointer const_void_pointer;
	typedef Allocator allocator_type;
	
	public:

	explicit stack_allocator(const allocator_type& alloc = allocator_type()) 
		: m_allocator(alloc), m_begin(nullptr), m_end(nullptr), m_stack_pointer(nullptr)
	{ }

	explicit stack_allocator(pointer buffer, const allocator_type& alloc = allocator_type())
		: m_allocator(alloc), m_begin(buffer), m_end(buffer + N), 
			m_stack_pointer(buffer)
	{ }

	template <class U>
	stack_allocator(const stack_allocator<U, N, Allocator>& other)
		: m_allocator(other.m_allocator), m_begin(other.m_begin), m_end(other.m_end),
			m_stack_pointer(other.m_stack_pointer)
	{ }

	constexpr static size_type capacity()
	{
		return N;
	}

	pointer allocate(size_type n, const_void_pointer hint = const_void_pointer())
	{
		if (n <= size_type(std::distance(m_stack_pointer, m_end)))
		{
			pointer result = m_stack_pointer;
			m_stack_pointer += n;
			return result;
		}

		return m_allocator.allocate(n, hint);
	}

	void deallocate(pointer p, size_type n)
	{
		if (pointer_to_internal_buffer(p))
		{
			m_stack_pointer -= n;
		}
		else m_allocator.deallocate(p, n);	
	}

	size_type max_size() const noexcept
	{
		return m_allocator.max_size();
	}

	template <class U, class... Args>
	void construct(U* p, Args&&... args)
	{
		m_allocator.construct(p, std::forward<Args>(args)...);
	}

	template <class U>
	void destroy(U* p)
	{
		m_allocator.destroy(p);
	}

	pointer address(reference x) const noexcept
	{
		if (pointer_to_internal_buffer(std::addressof(x)))
		{
			return std::addressof(x);
		}

		return m_allocator.address(x);
	}
	
	const_pointer address(const_reference x) const noexcept
	{
		if (pointer_to_internal_buffer(std::addressof(x)))
		{
			return std::addressof(x);
		}

		return m_allocator.address(x);
	}

	template <class U>
	struct rebind { typedef stack_allocator<U, N, allocator_type> other; };

	pointer buffer() const noexcept
	{
		return m_begin;
	}

	private:

	bool pointer_to_internal_buffer(const_pointer p) const
	{
		return (!(std::less<const_pointer>()(p, m_begin)) && (std::less<const_pointer>()(p, m_end)));
	}

	allocator_type m_allocator;
	pointer m_begin;
	pointer m_end;
	pointer m_stack_pointer;
};

template <class T1, std::size_t N, class Allocator, class T2>
bool operator == (const stack_allocator<T1, N, Allocator>& lhs, 
	const stack_allocator<T2, N, Allocator>& rhs) noexcept
{
	return lhs.buffer() == rhs.buffer();
}

template <class T1, std::size_t N, class Allocator, class T2>
bool operator != (const stack_allocator<T1, N, Allocator>& lhs, 
	const stack_allocator<T2, N, Allocator>& rhs) noexcept
{
	return !(lhs == rhs);
}

// -------- Specialization for void
//
template <std::size_t N, class Allocator>
class stack_allocator<void, N, Allocator>
{
	public:

	typedef std::size_t size_type;
	typedef std::ptrdiff_t difference_type;
	typedef void* pointer;
	typedef const void* const_pointer;
	typedef void value_type;

	constexpr pointer buffer() const noexcept
	{
		return nullptr;
	}

	template <class U>
	struct rebind
	{
		typedef stack_allocator<U, N, typename Allocator::template rebind<U>::other> other;
	};
};

#endif
