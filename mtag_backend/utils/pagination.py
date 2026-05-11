from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        from utils.response import success_response
        return success_response(
            data=data,
            meta={
                'count': self.page.paginator.count,
                'next': self.get_next_link(),
                'previous': self.get_previous_link(),
                'total_pages': self.page.paginator.num_pages,
                'current_page': self.page.number,
            }
        )
